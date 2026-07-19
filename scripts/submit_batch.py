#!/usr/bin/env python3
"""Batch-screen candidate WQ alphas using conservative heuristics.

This script does not blindly submit every expression. Instead it:
1. Simulates each candidate expression.
2. Reads the resulting alpha metrics from BRAIN.
3. Rejects obvious failures early.
4. Optionally submits only those that clear the minimum thresholds.

Usage examples:
    python scripts/submit_batch.py
    python scripts/submit_batch.py --expression "group_rank(ts_rank(operating_income / equity, 126), subindustry)"
    python scripts/submit_batch.py --candidates-file candidates.json --submit
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
import requests

try:
    from evolve_skill import (
        create_session,
        daily_returns,
        fetch_pnl,
        fetch_user_alphas,
    )
except ModuleNotFoundError:  # pragma: no cover - exercised when imported as a package
    from scripts.evolve_skill import (  # type: ignore
        create_session,
        daily_returns,
        fetch_pnl,
        fetch_user_alphas,
    )


__all__ = ["build_active_alpha_context"]


DEFAULT_SETTINGS = {
    "instrumentType": "EQUITY",
    "region": "USA",
    "universe": "TOP3000",
    "delay": 1,
    "decay": 0,
    "neutralization": "SUBINDUSTRY",
    "truncation": 0.08,
    "pasteurization": "ON",
    "unitHandling": "VERIFY",
    "nanHandling": "ON",
    "language": "FASTEXPR",
    "visualization": False,
}

DEFAULT_THRESHOLDS = {
    "min_sharpe": 1.3,
    "min_fitness": 1.1,
    "max_turnover": 0.35,
    "max_drawdown": 0.15,
    "max_corr": 0.7,
}

DEFAULT_CANDIDATES = [
    {
        "name": "baseline_profitability",
        "expression": "group_rank(ts_rank(operating_income / equity, 126), subindustry)",
    },
    {
        "name": "analyst_eps",
        "expression": "group_rank(ts_rank(est_eps / close, 126), industry)",
    },
    {
        "name": "mixed_fundamental_analyst",
        "expression": "0.5 * group_rank(ts_rank(operating_income / equity, 126), subindustry) + 0.5 * group_rank(ts_rank(est_eps / close, 126), industry)",
    },
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Batch-screen candidate WQ alphas")
    parser.add_argument("--candidates-file", type=Path, help="JSON file with an array of candidate objects")
    parser.add_argument("--expression", action="append", help="Expression to test. Repeat for multiple expressions")
    parser.add_argument("--name", action="append", help="Optional label for each --expression")
    parser.add_argument("--submit", action="store_true", help="Submit candidates that pass the thresholds")
    parser.add_argument("--json-output", type=Path, help="Optional path to save the batch report as JSON")
    return parser.parse_args()


def load_candidates(args: argparse.Namespace) -> list[dict[str, Any]]:
    if args.candidates_file:
        data = json.loads(args.candidates_file.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            items = data.get("candidates", [])
        elif isinstance(data, list):
            items = data
        else:
            raise ValueError("Candidates file must contain a list or an object with a 'candidates' list")
        out = []
        for item in items:
            if isinstance(item, str):
                out.append({"name": "candidate", "expression": item})
            elif isinstance(item, dict):
                out.append({
                    "name": item.get("name", "candidate"),
                    "expression": item.get("expression"),
                    "settings": item.get("settings") or DEFAULT_SETTINGS,
                })
            else:
                raise ValueError("Each candidate must be a string or an object")
        return out

    if args.expression:
        names = args.name or []
        out = []
        for idx, expr in enumerate(args.expression):
            name = names[idx] if idx < len(names) else f"expression_{idx + 1}"
            out.append({"name": name, "expression": expr, "settings": DEFAULT_SETTINGS})
        return out

    return [
        {"name": item["name"], "expression": item["expression"], "settings": DEFAULT_SETTINGS}
        for item in DEFAULT_CANDIDATES
    ]


def post_with_retry(session: requests.Session, url: str, **kwargs: Any) -> requests.Response:
    while True:
        resp = session.post(url, **kwargs)
        if resp.status_code == 429:
            retry_after = int(resp.headers.get("Retry-After", 5))
            time.sleep(retry_after)
            continue
        return resp


def simulate_candidate(session: requests.Session, expression: str, settings: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "type": "REGULAR",
        "settings": settings,
        "regular": expression,
    }
    resp = post_with_retry(session, "https://api.worldquantbrain.com/simulations", json=payload)
    if resp.status_code != 201:
        return {"ok": False, "error": f"simulation_failed:{resp.status_code}", "body": resp.text}

    location = resp.headers.get("Location", "")
    if not location:
        return {"ok": False, "error": "missing_location_header", "body": resp.text}

    sim_id = location.rstrip("/").split("/")[-1]
    for _ in range(60):
        time.sleep(4)
        poll = session.get(f"https://api.worldquantbrain.com/simulations/{sim_id}")
        if poll.status_code != 200:
            continue
        data = poll.json()
        status = data.get("status")
        if status == "COMPLETE":
            alpha_id = data.get("alpha")
            if alpha_id:
                return {"ok": True, "alpha_id": alpha_id}
            return {"ok": False, "error": "missing_alpha_id", "body": data}
        if status in {"ERROR", "FAILED"}:
            return {"ok": False, "error": "simulation_error", "body": data}
    return {"ok": False, "error": "simulation_timeout", "body": {}}


def compute_best_correlation(new_pnl: list[float], active_alphas: list[dict[str, Any]]) -> tuple[float | None, str | None]:
    if len(new_pnl) < 60:
        return None, None
    new_ret = np.array(daily_returns(new_pnl))
    best_corr = None
    best_id = None
    for alpha in active_alphas:
        old_pnl = alpha.get("pnl") or []
        if len(old_pnl) < 60:
            continue
        old_ret = np.array(daily_returns(old_pnl))
        if len(new_ret) != len(old_ret):
            continue
        corr = float(np.corrcoef(new_ret, old_ret)[0, 1])
        if best_corr is None or abs(corr) > abs(best_corr):
            best_corr = corr
            best_id = alpha.get("id")
    return best_corr, best_id


def evaluate_candidate(session: requests.Session, candidate: dict[str, Any], thresholds: dict[str, float], active_alphas: list[dict[str, Any]]) -> dict[str, Any]:
    sim = simulate_candidate(session, candidate["expression"], candidate.get("settings") or DEFAULT_SETTINGS)
    if not sim.get("ok"):
        return {
            "name": candidate["name"],
            "expression": candidate["expression"],
            "decision": "reject",
            "reason": sim.get("error"),
            "details": sim.get("body"),
        }

    alpha_id = sim["alpha_id"]
    alpha_resp = session.get(f"https://api.worldquantbrain.com/alphas/{alpha_id}")
    if alpha_resp.status_code != 200:
        return {
            "name": candidate["name"],
            "expression": candidate["expression"],
            "decision": "reject",
            "reason": f"alpha_fetch_failed:{alpha_resp.status_code}",
            "details": alpha_resp.text,
        }

    alpha = alpha_resp.json()
    is_ = alpha.get("is", {}) or {}
    metrics = {
        "sharpe": is_.get("sharpe"),
        "fitness": is_.get("fitness"),
        "turnover": is_.get("turnover"),
        "drawdown": is_.get("drawdown"),
        "returns": is_.get("returns"),
        "margin": is_.get("margin"),
    }

    checks = {c.get("name"): c for c in alpha.get("is", {}).get("checks", []) if isinstance(c, dict) and c.get("name")}
    self_corr = checks.get("SELF_CORRELATION", {})
    self_corr_result = self_corr.get("result")

    new_pnl = fetch_pnl(session, alpha_id)
    best_corr, best_id = compute_best_correlation(new_pnl, active_alphas)

    reasons = []
    if metrics.get("sharpe") is None or metrics.get("sharpe") < thresholds["min_sharpe"]:
        reasons.append("low_sharpe")
    if metrics.get("fitness") is None or metrics.get("fitness") < thresholds["min_fitness"]:
        reasons.append("low_fitness")
    if metrics.get("turnover") is not None and metrics.get("turnover") > thresholds["max_turnover"]:
        reasons.append("high_turnover")
    if metrics.get("drawdown") is not None and metrics.get("drawdown") > thresholds["max_drawdown"]:
        reasons.append("high_drawdown")
    if self_corr_result == "FAIL":
        reasons.append("self_correlation_fail")
    if best_corr is not None and abs(best_corr) >= thresholds["max_corr"]:
        reasons.append("high_correlation")

    if reasons:
        decision = "review"
        if any(r in {"self_correlation_fail", "high_correlation"} for r in reasons):
            decision = "reject"
        return {
            "name": candidate["name"],
            "expression": candidate["expression"],
            "alpha_id": alpha_id,
            "decision": decision,
            "metrics": metrics,
            "self_correlation": self_corr_result,
            "best_corr": best_corr,
            "best_corr_alpha_id": best_id,
            "reasons": reasons,
        }

    return {
        "name": candidate["name"],
        "expression": candidate["expression"],
        "alpha_id": alpha_id,
        "decision": "candidate",
        "metrics": metrics,
        "self_correlation": self_corr_result,
        "best_corr": best_corr,
        "best_corr_alpha_id": best_id,
        "reasons": [],
    }


def submit_if_requested(session: requests.Session, result: dict[str, Any]) -> dict[str, Any]:
    if result.get("decision") != "candidate":
        return result

    alpha_id = result.get("alpha_id")
    if not alpha_id:
        return result

    submit_resp = post_with_retry(session, f"https://api.worldquantbrain.com/alphas/{alpha_id}/submit")
    if submit_resp.status_code not in {200, 201}:
        result["decision"] = "submit_failed"
        result["submit_status"] = submit_resp.status_code
        return result

    for _ in range(20):
        time.sleep(8)
        alpha_resp = session.get(f"https://api.worldquantbrain.com/alphas/{alpha_id}")
        if alpha_resp.status_code != 200:
            continue
        alpha = alpha_resp.json()
        status = alpha.get("status")
        if status == "ACTIVE":
            result["decision"] = "submitted"
            result["submit_status"] = status
            result["submitted_status"] = status
            return result

    result["decision"] = "verify_failed"
    result["submit_status"] = submit_resp.status_code
    return result


def build_active_alpha_context(
    session: requests.Session,
    max_active_alphas: int = 30,
    fetch_user_alphas_fn: Any = None,
    fetch_pnl_fn: Any = None,
) -> list[dict[str, Any]]:
    fetch_user_alphas_fn = fetch_user_alphas_fn or fetch_user_alphas
    fetch_pnl_fn = fetch_pnl_fn or fetch_pnl

    all_alphas = fetch_user_alphas_fn(session)
    active_alphas: list[dict[str, Any]] = []
    for alpha in all_alphas:
        alpha_id = alpha.get("id")
        if not alpha_id or alpha.get("status") != "ACTIVE":
            continue
        pnl = fetch_pnl_fn(session, alpha_id)
        if not pnl:
            continue
        alpha_entry = dict(alpha)
        alpha_entry["pnl"] = pnl
        active_alphas.append(alpha_entry)
        if len(active_alphas) >= max_active_alphas:
            break
    return active_alphas


def main() -> int:
    args = parse_args()
    session = create_session()

    # Fetch a bounded set of current ACTIVE alpha context for correlation checks.
    active_alphas = build_active_alpha_context(session)

    candidates = load_candidates(args)
    results = []
    for candidate in candidates:
        result = evaluate_candidate(session, candidate, DEFAULT_THRESHOLDS, active_alphas)
        if args.submit:
            result = submit_if_requested(session, result)
        results.append(result)

    for item in results:
        print("\n" + "=" * 72)
        print(f"Name: {item['name']}")
        print(f"Expression: {item['expression']}")
        print(f"Decision: {item['decision']}")
        if item.get("alpha_id"):
            print(f"Alpha ID: {item['alpha_id']}")
        if item.get("metrics"):
            print("Metrics:")
            for key in ("sharpe", "fitness", "turnover", "drawdown", "returns", "margin"):
                val = item["metrics"].get(key)
                if val is not None:
                    print(f"  - {key}: {val}")
        if item.get("self_correlation") is not None:
            print(f"Self-correlation: {item['self_correlation']}")
        if item.get("best_corr") is not None:
            print(f"Best corr vs active: {item['best_corr']:.3f} ({item['best_corr_alpha_id']})")
        if item.get("reasons"):
            print(f"Reasons: {', '.join(item['reasons'])}")

    if args.json_output:
        args.json_output.write_text(json.dumps(results, indent=2), encoding="utf-8")

    return 0


if __name__ == "__main__":
    sys.exit(main())
