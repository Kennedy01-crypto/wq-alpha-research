---
name: wq-alpha-research
description: "Use for WorldQuant BRAIN alpha research: designing WQ Alpha expressions, selecting fields/operators, diagnosing simulation and IS check failures, tuning Sharpe/Fitness/Turnover, submitting alphas, and building low-correlation alpha portfolios. Also use for English requests about WorldQuant, BRAIN, WQ Alpha, factor expressions, backtests, submissions, turnover, Fitness, and Sharpe."
---

# WQ Alpha Research Skill

> Structured playbook: field → expression → backtest → check → submit → combine. It combines WorldQuant BRAIN documentation knowledge with empirical experience from the USA TOP3000 universe.

---

## 1. Quick Decision Tree

```
Start
  ├── Fetch all alpha list ──→ look only at ACTIVE; compute **daily return** correlation, and revise or discard if it exceeds 0.7
  ├── Design a new factor
  │    ├── Is the field verified? ──No──→ go to Section 2 (local field file search / simulate rank(field))
  │    └── Yes
  │         ├── Fundamental ──→ group_rank + ts_rank, SUBINDUSTRY, decay=0
  │         ├── Analyst ──→ group_rank + ts_rank, INDUSTRY/SUBINDUSTRY, decay=0–4
  │         ├── Technical ────→ high decay (10–30) or mix with fundamentals to reduce turnover
  │         └── Sentiment ────→ nanHandling=ON, use caution with small windows
  └── After submission ──→ verify status == ACTIVE; otherwise inspect SELF_CORRELATION
```

### 1.1 Diversification Rules for Low-Correlation Portfolios

Before drafting a new alpha, deliberately choose a different signal family from the one used in the previous submission. The goal is not to make a slightly different version of the same idea; it is to add a genuinely distinct factor to the portfolio.

Practical rules:

1. Pick a different data cluster than the last submitted alpha: fundamental, analyst, price/volume, news, option, or model.
2. Use a different operator family from the previous idea. For example, if the last alpha was a `group_rank + ts_rank` analyst factor, the next one should not be another analyst-style ranker unless it is clearly stronger and less correlated.
3. Prefer a cross-cluster contrast such as fundamental → price/volume or analyst → event/news rather than a near-duplicate from the same cluster.
4. Require a strong correlation check before submission: below 0.5 is safe, 0.5–0.7 is caution, and above 0.7 should be rejected unless the Sharpe is meaningfully better.
5. If metrics look good but the correlation is still high, change the field family or the transformation rather than just tweaking the window.

A good portfolio should not contain multiple alphas that are basically the same signal under different windows.

---

## 2. Field Quick Reference (Local Dataset)

This skill already includes the complete field list for USA TOP3000 with delay=1 (4,367 fields), so there is no need to fetch from the web/API each time:

- `references/wq_usa_top3000_delay1_data_fields.json`: full field metadata array
- `references/wq_usa_top3000_delay1_data_fields.csv`: CSV version for Excel/pandas use
- `references/wq_usa_top3000_delay1_data_fields_summary.json`: category statistics and sample fields

Field distribution:

| Category    | Count | Description                                  |
| ----------- | ----- | -------------------------------------------- |
| fundamental | 1652  | financial statements and footnote accounts   |
| analyst     | 1324  | analyst expectations and consensus estimates |
| news        | 996   | news and earnings event data                 |
| pv          | 195   | price/volume, ADV, VWAP, etc.                |
| option      | 138   | option implied volatility, put/call, etc.    |
| model       | 40    | model factors                                |
| socialmedia | 22    | social media sentiment                       |
| univ1       | 6     | universe-related fields                      |

### 2.1 Search Fields Locally

```python
import json
from pathlib import Path

# Assume you run this from the skill directory; if not, use the actual path
skill_dir = Path(".")
field_dir = skill_dir / "references"
data = json.loads((field_dir / "wq_usa_top3000_delay1_data_fields.json").read_text(encoding="utf-8"))

keyword = "operating_income"
matches = [
    f for f in data
    if keyword.lower() in f["id"].lower()
    or (f.get("description") and keyword.lower() in f["description"].lower())
]

for f in matches[:10]:
    print(f"{f['id']} | {f.get('category',{}).get('name')} | {f.get('dataset',{}).get('name')} | coverage={f.get('coverage')} | alphaCount={f.get('alphaCount')}")
```

### 2.2 Filter by Category

```python
category = "pv"  # or fundamental / analyst / news / option / model / socialmedia
fields = [f for f in data if f.get("category", {}).get("id") == category]
print(f"{category}: {len(fields)} fields")
for f in sorted(fields, key=lambda x: x.get("alphaCount", 0), reverse=True)[:10]:
    print(f"  {f['id']} | alphaCount={f.get('alphaCount')} | coverage={f.get('coverage')}")
```

### 2.3 Field Validation

After selecting a candidate field, first validate that it is genuinely usable with a simple expression simulation:

```python
payload = {
    "type": "REGULAR",
    "settings": {
        "instrumentType": "EQUITY", "region": "USA", "universe": "TOP3000",
        "delay": 1, "decay": 0, "neutralization": "MARKET",
        "truncation": 0.08, "pasteurization": "ON", "unitHandling": "VERIFY",
        "nanHandling": "ON", "language": "FASTEXPR", "visualization": False,
    },
    "regular": "rank(my_candidate_field)",
}
resp = session.post("https://api.worldquantbrain.com/simulations", json=payload)
# 201 means the field is usable; a non-201 usually indicates the field does not exist or the parameters do not match
```

### 2.4 When to Refresh the Local Dataset

The local field set already covers USA TOP3000 with delay=1. Refresh from BRAIN only when:

- You change the region (for example, CHN or EUR)
- You change the universe (for example, TOP500 or TOP1000)
- You change the delay (for example, 0)
- The BRAIN platform field list has clearly changed (compare `dateCreated` with the local copy)

---

## 3. Operator Quick Reference

| Type            | Operator                                                                                                      | Purpose                                        |
| --------------- | ------------------------------------------------------------------------------------------------------------- | ---------------------------------------------- |
| Cross-sectional | `rank(x)`, `zscore(x)`, `normalize(x)`, `scale(x)`, `winsorize(x, std=4)`                                     | Standardize all stocks each day                |
| Time-series     | `ts_mean`, `ts_std_dev`, `ts_delta`, `ts_rank`, `ts_corr`, `ts_decay_linear`, `ts_backfill`, `ts_zscore`      | Compute historical window values for one stock |
| Group           | `group_rank(x, group)`, `group_neutralize(x, group)`, `group_zscore(x, group)`, `group_backfill(x, group, N)` | Neutralize within groups                       |
| Conditional     | `if_else(cond, a, b)`, `trade_when(x, cond, delay)`                                                           | Apply conditional exposure                     |
| Vector          | `vec_avg(a, b, c)`, `vec_sum(a, b, c)`                                                                        | Average/sum multiple fields elementwise        |

**Golden combination**: `group_rank(ts_rank(signal, N), subindustry)`

---

## 4. Factor Template Library

### 4.1 High-Probability Templates

```fastexpr
-- Template A: ROE trend (highest pass rate)
group_rank(ts_rank(operating_income / equity, 126), subindustry)

-- Template B: EPS yield adjustment
group_rank(ts_rank(est_eps / close, 126), industry)

-- Template C: FCF yield
group_rank(ts_rank(free_cash_flow_reported_value / equity, 126), industry)

-- Template D: multi-factor blend (high Fitness)
0.5 * group_rank(ts_rank(operating_income / equity, 126), subindustry)
+ 0.5 * group_rank(ts_rank(est_eps / close, 126), industry)

-- Template E: low-correlation technical + fundamental blend
0.5 * rank(-(close / open - 1)) + 0.5 * rank(ts_rank(operating_income / equity, 126))

-- Template F: asset turnover × profit margin
rank(ts_rank(operating_income / sales * sales / assets, 126))
```

### 4.2 Recommended Defaults

| Factor Type          | Decay | Neutralization       | Truncation | nanHandling | Expected TO |
| -------------------- | ----- | -------------------- | ---------- | ----------- | ----------- |
| Fundamental quality  | 0     | SUBINDUSTRY          | 0.08       | ON          | 2–8%        |
| Analyst expectations | 0–4   | INDUSTRY/SUBINDUSTRY | 0.08       | ON          | 9–16%       |
| Technical reversal   | 10–30 | INDUSTRY             | 0.08       | OFF         | 15–35%      |
| Mixed factors        | 4–20  | INDUSTRY/SUBINDUSTRY | 0.08       | ON          | 10–20%      |
| Sentiment            | 4–10  | INDUSTRY             | 0.05–0.08  | ON          | 8–30%       |

---

## 5. Metrics and Checks

### 5.1 Core Metrics

| Metric   | Formula/Meaning                | Target               |
| -------- | ------------------------------ | -------------------- | ----------------- | ------------------- |
| Sharpe   | daily IR × √252                | ≥ 1.5 (minimum 1.25) |
| Fitness  | Sharpe × √(                    | Returns              | / max(TO, 0.125)) | ≥ 1.1 (minimum 1.0) |
| Returns  | annualized return / $10M       | ≥ 7%                 |
| Turnover | daily traded value / Book Size | 1%–20%               |
| Drawdown | maximum peak-to-trough decline | < 15%                |
| Margin   | PnL / total traded value       | higher is better     |

### 5.2 IS Check List

| Check                   | Threshold                                 | Failure Cause                   | Fix                                                                                         |
| ----------------------- | ----------------------------------------- | ------------------------------- | ------------------------------------------------------------------------------------------- |
| LOW_SHARPE              | ≥ 1.25                                    | weak signal                     | change field/window or add group_rank                                                       |
| LOW_FITNESS             | ≥ 1.0                                     | turnover too high               | increase decay or blend a more stable signal                                                |
| LOW_TURNOVER            | ≥ 1%                                      | signal too stable               | shorten the window or use a more active field                                               |
| HIGH_TURNOVER           | ≤ 70%                                     | turnover explosion              | increase decay, use trade_when, or blend                                                    |
| CONCENTRATED_WEIGHT     | single-stock weight < 10% and diversified | concentrated weights            | use rank(), reduce truncation, use ts_backfill                                              |
| LOW_SUB_UNIVERSE_SHARPE | also effective in TOP1000                 | small-cap dependence            | use fundamentals, SUBINDUSTRY, avoid market-cap bias                                        |
| SELF_CORRELATION        | daily-return correlation < 0.7            | too similar to existing factors | change the signal cluster, add filters, or change the universe; do not just tune parameters |
| MATCHES_COMPETITION     | informational                             | —                               | no impact                                                                                   |

### 5.3 Failure Statistics

| Failure Cause           | Share | Conclusion                                |
| ----------------------- | ----- | ----------------------------------------- |
| LOW_SHARPE              | 90.7% | signal quality is the main bottleneck     |
| LOW_FITNESS             | 66.2% | usually a softer version of HIGH_TURNOVER |
| LOW_SUB_UNIVERSE_SHARPE | 51.0% | avoid small-cap/liquidity bias            |

**Pass rate by data type**: fundamental 40% > mixed 12.7% > pure technical 5.3% > other 0%

---

## 6. Problem Diagnosis and Fixes

| Symptom                  | Likely Cause                                   | Fix                                                                               |
| ------------------------ | ---------------------------------------------- | --------------------------------------------------------------------------------- |
| Fitness < 1.0            | turnover > 30%                                 | increase decay, blend fundamentals, use ts_decay_linear                           |
| Sharpe < 1.25            | weak signal                                    | lengthen the window, use group_rank, change the field                             |
| TO > 50%                 | signal changes too quickly                     | decay 10–30, trade_when, blend                                                    |
| DD > 15%                 | high volatility / leverage                     | increase decay, reduce truncation, blend lower-volatility signals                 |
| CONCENTRATED_WEIGHT FAIL | sparsity / extreme values                      | use rank(), truncation 0.05, ts_backfill                                          |
| Sub-Universe FAIL        | small-cap dependence                           | avoid `rank(-assets)`, use group_rank, add liquidity filtering                    |
| simulation_error         | field does not exist / operator argument error | first validate the field with rank(field), then check the operator argument count |
| trade_when zero trades   | conditions are too strict                      | relax the condition or use if_else                                                |

---

## 7. BRAIN API Automation

### 7.1 Authentication (Please Fill in Your Account)

**You must prepare credentials before use.** The recommended approach is environment variables. Alternatively, you can place an untracked `credential.txt` locally (ignored by `.gitignore`) containing a JSON array:

```json
["your_username", "your_password"]
```

⚠️ **Reminder**: do not write real account credentials into the repository. Prefer the `WQ_BRAIN_USERNAME` / `WQ_BRAIN_PASSWORD` environment variables.

```python
import json
import requests
from requests.auth import HTTPBasicAuth

API_BASE = "https://api.worldquantbrain.com"

# 1. Read credential.txt
import os

username = os.getenv("WQ_BRAIN_USERNAME")
password = os.getenv("WQ_BRAIN_PASSWORD")
if not (username and password):
    with open("credential.txt") as f:
        username, password = json.load(f)

# 2. Create a session and authenticate
session = requests.Session()
session.auth = HTTPBasicAuth(username, password)
session.headers.update({
    "Content-Type": "application/json",
    "Accept": "application/json",
})

resp = session.post(f"{API_BASE}/authentication")
assert resp.status_code == 201, f"Authentication failed: {resp.status_code} {resp.text}"
print("Authentication successful")
```

### 7.2 Fetch Submitted Alphas and Compute Correlation

**Goal**: before submitting a new factor, avoid high correlation with existing factor PnL (correlation coefficient ≥ 0.7).

```python
import numpy as np

def fetch_pnl(session, alpha_id):
    """Get the cumulative PnL series for an alpha; schema.properties may be a list or a dict."""
    r = session.get(f"{API_BASE}/alphas/{alpha_id}/recordsets/pnl")
    if r.status_code != 200 or not r.text.strip():
        return []
    data = r.json()
    props = data.get("schema", {}).get("properties", [])
    if isinstance(props, list):
        date_idx = next((i for i, p in enumerate(props) if p.get("name", "").lower() == "date"), 0)
        pnl_idx = next((i for i, p in enumerate(props) if p.get("name", "").lower() in ("pnl", "cum_pnl", "returns", "ret")), 1)
    else:
        date_idx = next((v["index"] for k, v in props.items() if k.lower() == "date"), 0)
        pnl_idx = next((v["index"] for k, v in props.items() if k.lower() in ("pnl", "cum_pnl", "returns", "ret")), 1)
    records = sorted(data.get("records", []), key=lambda r: r[date_idx])
    out = []
    for row in records:
        rec = row[0] if isinstance(row, list) and len(row) == 1 and isinstance(row[0], list) else row
        try:
            out.append(float(rec[pnl_idx]))
        except Exception:
            continue
    return out

def daily_returns(cum_pnl):
    """Convert cumulative PnL to daily returns; correlation should be based on daily returns rather than the cumulative curve."""
    return [cum_pnl[i+1] - cum_pnl[i] for i in range(len(cum_pnl) - 1)]

def get_active_alphas(session, user_id="self", limit=100):
    """Get all alphas (including ACTIVE / UNSUBMITTED), paging as needed."""
    all_alphas = []
    offset = 0
    while True:
        data = session.get(f"{API_BASE}/users/{user_id}/alphas", params={"limit": limit, "offset": offset}).json()
        batch = data.get("results", data.get("alphas", []))
        if not batch:
            break
        all_alphas.extend(batch)
        if len(batch) < limit:
            break
        offset += limit
    return all_alphas

# Compute the daily-return correlation between the new factor and all ACTIVE alphas
new_pnl = fetch_pnl(session, new_alpha_id)
new_ret = daily_returns(new_pnl)
existing = get_active_alphas(session)
active = [a for a in existing if a.get("status") == "ACTIVE"]

high_corr = []
for alpha in active:
    old_id = alpha.get("id")
    try:
        old_pnl = fetch_pnl(session, old_id)
        old_ret = daily_returns(old_pnl)
        if len(new_ret) == len(old_ret) and len(new_ret) > 20:
            corr = float(np.corrcoef(new_ret, old_ret)[0, 1])
            print(f"Correlation with {old_id} on daily returns: {corr:.3f}")
            if abs(corr) >= 0.7:
                high_corr.append((old_id, corr))
    except Exception:
        continue

if high_corr:
    print(f"⚠️ Found {len(high_corr)} highly correlated factors; consider revising or discarding them")
```

**Decision rule (based on daily returns, not cumulative PnL)**:

| Correlation           | Action                                                                                            |
| --------------------- | ------------------------------------------------------------------------------------------------- |
| abs(corr) < 0.5       | ✅ Safe to submit                                                                                 |
| 0.5 ≤ abs(corr) < 0.7 | ⚠️ Use caution; improve Sharpe or change the signal                                               |
| abs(corr) ≥ 0.7       | ❌ Discard or restructure (unless the new factor Sharpe is at least 1.1× the old factor's Sharpe) |

> ⚠️ **Do not compute correlation from cumulative PnL.** The cumulative curve has a strong built-in trend and can seriously exaggerate similarity between different signals.

### 7.3 Backtest

```python
payload = {
    "type": "REGULAR",
    "settings": {
        "instrumentType": "EQUITY", "region": "USA", "universe": "TOP3000",
        "delay": 1, "decay": 0, "neutralization": "SUBINDUSTRY",
        "truncation": 0.08, "pasteurization": "ON", "unitHandling": "VERIFY",
        "nanHandling": "ON", "language": "FASTEXPR", "visualization": False,
    },
    "regular": "group_rank(ts_rank(operating_income/equity, 126), subindustry)",
}
resp = session.post("https://api.worldquantbrain.com/simulations", json=payload)
sim_id = resp.headers["Location"].rstrip("/").split("/")[-1]

while True:
    data = session.get(f"https://api.worldquantbrain.com/simulations/{sim_id}").json()
    if data.get("status") == "COMPLETE":
        alpha_id = data["alpha"]
        break
    time.sleep(8)

alpha = session.get(f"https://api.worldquantbrain.com/alphas/{alpha_id}").json()
```

### 7.4 Submit and Monitor

```python
# Submit
sub = session.post(f"https://api.worldquantbrain.com/alphas/{alpha_id}/submit")
print(sub.status_code)  # 201 means accepted

# Monitor SELF_CORRELATION
for _ in range(30):
    alpha = session.get(f"https://api.worldquantbrain.com/alphas/{alpha_id}").json()
    sc = next((c for c in alpha.get("is", {}).get("checks", []) if c["name"] == "SELF_CORRELATION"), {})
    if sc.get("result") in ("PASS", "FAIL"):
        break
    time.sleep(60)
```

### 7.5 Automated Submission Template

```python
import numpy as np

def simulate_and_submit(expression, settings, existing_pnls=None):
    """
    existing_pnls: {alpha_id: [cum_pnl_values]} – cumulative PnL series of already live factors.
    Returns: {"alpha_id": ..., "decision": "submitted|skip|high_corr|verify_failed", ...}
    """
    payload = {"type": "REGULAR", "settings": settings, "regular": expression}
    resp = session.post("https://api.worldquantbrain.com/simulations", json=payload)
    if resp.status_code != 201:
        return {"error": "simulate_failed"}
    sim_id = resp.headers["Location"].rstrip("/").split("/")[-1]
    while True:
        data = session.get(f"https://api.worldquantbrain.com/simulations/{sim_id}").json()
        if data.get("status") == "COMPLETE":
            alpha_id = data["alpha"]
            break
        if data.get("status") in ("ERROR", "FAILED"):
            return {"error": "simulation_error"}
        time.sleep(8)
    alpha = session.get(f"https://api.worldquantbrain.com/alphas/{alpha_id}").json()
    is_ = alpha.get("is", {})

    # 1. Basic metric filtering
    if is_.get("fitness", 0) < 1.1 or is_.get("sharpe", 0) < 1.3 or is_.get("turnover", 1) > 0.20:
        return {"alpha_id": alpha_id, "decision": "skip", "reason": "metrics", "metrics": is_}

    # 2. Correlation check (based on daily returns)
    def daily_rets(cum):
        return [cum[i+1] - cum[i] for i in range(len(cum) - 1)]

    if existing_pnls:
        new_pnl = fetch_pnl(session, alpha_id)
        new_ret = daily_rets(new_pnl)
        for old_id, old_pnl in existing_pnls.items():
            old_ret = daily_rets(old_pnl)
            if len(new_ret) == len(old_ret) and len(new_ret) > 20:
                corr = abs(float(np.corrcoef(new_ret, old_ret)[0, 1]))
                if corr >= 0.7:
                    # Exception: a new factor can be submitted if its Sharpe is more than 10% above the old one
                    old_sharpe = None  # needs to be passed in externally or cached
                    if old_sharpe is None or is_.get("sharpe", 0) < old_sharpe * 1.1:
                        return {"alpha_id": alpha_id, "decision": "high_corr", "corr_with": old_id, "corr": corr}

    # 3. Submit
    sub = session.post(f"https://api.worldquantbrain.com/alphas/{alpha_id}/submit")
    if sub.status_code not in (200, 201):
        return {"alpha_id": alpha_id, "decision": "submit_failed", "status": sub.status_code}

    # 4. Verify that it is truly live (BRAIN may keep it UNSUBMITTED because of SELF_CORRELATION)
    for _ in range(20):
        time.sleep(10)
        alpha = session.get(f"https://api.worldquantbrain.com/alphas/{alpha_id}").json()
        if alpha.get("status") == "ACTIVE":
            return {"alpha_id": alpha_id, "decision": "submitted", "status": "ACTIVE"}
        sc = next((c for c in alpha.get("is", {}).get("checks", []) if c["name"] == "SELF_CORRELATION"), {})
        if sc.get("result") == "FAIL":
            return {"alpha_id": alpha_id, "decision": "self_correlation_fail", "status": alpha.get("status")}

    return {"alpha_id": alpha_id, "decision": "verify_failed", "status": alpha.get("status")}
```

### 7.6 Rate Limiting

- Wait 2–5 seconds between simulation and submission requests.
- When you see 429, read `Retry-After` and use exponential backoff.
- For batch work, use single-threading or at most 2 concurrent requests.

### 7.7 Post-Submission Verification (201 ≠ Live)

`POST /alphas/{id}/submit` returning 201 only means the request was accepted; it does not mean the alpha has become ACTIVE. In practice, this often happens when:

- The alpha status remains `UNSUBMITTED` (SELF_CORRELATION failed or review is still pending).
- A newly generated alpha with a slightly changed parameter set is considered a duplicate by the system and cannot be submitted for real.

**A second confirmation is required**:

```python
alpha = session.get(f"{API_BASE}/alphas/{alpha_id}").json()
print(alpha.get("status"))  # ACTIVE means the submission was successful

# If status == UNSUBMITTED, inspect the SELF_CORRELATION result in the checks
for c in alpha.get("is", {}).get("checks", []):
    print(c["name"], c.get("result"), c.get("value"))
```

**Get all alphas and count ACTIVE ones**:

```python
def get_all_alphas(session, limit=100):
    all_alphas = []
    offset = 0
    while True:
        data = session.get(f"{API_BASE}/users/self/alphas", params={"limit": limit, "offset": offset}).json()
        batch = data.get("results", data.get("alphas", []))
        if not batch:
            break
        all_alphas.extend(batch)
        if len(batch) < limit:
            break
        offset += limit
    return all_alphas

all_alphas = get_all_alphas(session)
active = [a for a in all_alphas if a.get("status") == "ACTIVE"]
print(f"total={len(all_alphas)}, ACTIVE={len(active)}")
```

---

## 8. Portfolio Construction Rules

### 8.1 Example Diversified Portfolio

| Cluster             | Representative Expression                                                                                  |
| ------------------- | ---------------------------------------------------------------------------------------------------------- |
| Profitability       | `group_rank(ts_rank(operating_income/equity, 126), subindustry)`                                           |
| Analyst             | `group_rank(ts_rank(est_eps/close, 252), subindustry)`                                                     |
| FCF                 | `group_rank(ts_rank(free_cash_flow_reported_value/equity, 126), industry)`                                 |
| Low-correlation mix | `0.5*rank(-(close/open-1)) + 0.5*rank(ts_rank(operating_income/equity, 126))`                              |
| Quality portfolio   | `0.5*group_rank(ts_rank(oi/equity,126),subindustry) + 0.5*group_rank(ts_rank(est_eps/close,126),industry)` |

### 8.2 Submission Priority

1. Different signal cluster from the last submitted alpha or the current active set
2. High Fitness (≥ 1.5) with low TO (< 15%)
3. If SELF_CORRELATION conflicts, keep the higher-Fitness version
4. Prefer a factor that improves diversity more than it improves raw Sharpe alone

### 8.3 The Truth About Correlation

An analysis of daily returns for ACTIVE alphas shows:

- **Very high correlation within the same signal cluster**:
  - Two open-close reversal + OI/Equity mixed factors (with different weights) have daily-return correlation **0.84**
  - Two analyst EPS factors have correlation **0.74**
  - Two leverage/quality factors (`-equity/assets` vs `liabilities/assets`) have correlation **0.84**
- **Cross-cluster diversification is not guaranteed**: an emotion alpha based on `scl12_buzz` and an analyst alpha based on `est_eps/close` still show correlation of **0.59–0.67**
- **Cumulative PnL correlation is severely distorted**: cumulative PnL values for alphas are commonly correlated at **> 0.90**, which makes it easy to incorrectly assume all factors are the same

**Conclusion**:

- Changing the window, weights, or neutralization cannot create true low correlation
- True low correlation comes from completely different data sources or economic logic (for example, macro events, option flow, cross-border data, alternative data)
- In a normal USA TOP3000 universe of fundamentals/price-volume/analyst signals, "low correlation" is often in the **0.3–0.6** range on daily returns; do not chase 0

---

## 9. Pre-Submission Checklist

- [ ] You have fetched **all** alpha lists (including ACTIVE / UNSUBMITTED), not just the current simulation
- [ ] The new factor has daily-return correlation < 0.7 with existing ACTIVE alphas (or the new Sharpe is at least 1.1× the old Sharpe)
- [ ] Correlation is computed from **daily returns**, not cumulative PnL
- [ ] The field has been validated
- [ ] The simulation has no errors
- [ ] Sharpe ≥ 1.3 (ideal ≥ 1.5)
- [ ] Fitness ≥ 1.1
- [ ] Turnover 1%–20% (can be relaxed to ≤ 35%)
- [ ] Drawdown < 15%
- [ ] All IS checks PASS
- [ ] Long/short sizing is reasonable
- [ ] After submission, **verify again that status == ACTIVE**; 201 does not mean the alpha is live

---

## 10. Core Lessons (One-Line Version)

1. **Fetch all ACTIVE alpha PnL before generating a new factor** to avoid highly correlated duplicates.
2. **Correlation must be computed on daily returns**; cumulative PnL correlation makes all factors look identical.
3. **A 201 response does not mean submission succeeded**: after submission, confirm that `status == ACTIVE`.
4. **Fundamentals > mixed > technical**: `operating_income/equity`, `est_eps/close`, and `free_cash_flow_reported_value/equity` are the safest starting points.
5. **group_rank + ts_rank is the golden combination**.
6. **SUBINDUSTRY neutralization has the highest pass rate**.
7. **Decay is the main lever for controlling turnover**: fundamentals use 0, technical factors use 10–30.
8. **A 50/50 orthogonal blend can reduce turnover, but it does not necessarily reduce correlation**; correlation comes from the signal source, not the weights.
9. **Validate the field first**; invalid fields fail almost immediately.
10. **True low correlation is hard to achieve in USA TOP3000**; expressions that look different often have high correlation within the same data pool.

---

## 11. Self-Evolution Mechanism

Each time you interact with BRAIN (submit, query, or analyze), the AI should write the new findings back into this skill so it evolves with real-world experience.

### 11.1 Trigger Conditions

Run `scripts/evolve_skill.py` whenever any of the following happens:

- One or more new alphas are submitted
- A batch of alphas is backtested
- The alpha status is queried and changes (for example, UNSUBMITTED → ACTIVE or it is rejected)
- A new field usability / failure pattern is discovered

### 11.2 How to Run It

**Prerequisite**: set `WQ_BRAIN_USERNAME` / `WQ_BRAIN_PASSWORD`, or place an untracked `credential.txt` in the skill directory containing a JSON array of your BRAIN credentials:

```json
["your_username", "your_password"]
```

```bash
# 1. Preview: generate suggested markdown snippets without modifying any files
pyenv exec python scripts/evolve_skill.py

# 2. Apply: append to SKILL.md and update alpha_db.json
pyenv exec python scripts/evolve_skill.py --apply
```

> Note: **preview mode without `--apply` does not modify `alpha_db.json` or `SKILL.md`**; you can review it first. The script only depends on `requests` and `numpy` and does **not** require the `wq-bus` project code. The data files are distributed with the skill.

The script will:

1. Fetch `/users/self/alphas` with pagination to obtain all alphas.
2. Compare the local `alpha_db.json` to find new alphas or status/metric changes.
3. Fetch `recordsets/pnl` for new alphas and compute their daily-return correlation with existing ACTIVE alphas.
4. Automatically generate experience entries (metric evaluation + correlation evaluation + expression summary).
5. Output a **bulk snapshot** on the first run and **incremental entries** on later runs.
6. In `--apply` mode, append the entries to `## 12. Empirical Records (Auto-Updated)` and save a local `alpha_db.json`.

### 11.3 How the AI Should Organize Experience

After the script runs, the AI should make a manual judgment about which entries are worth permanently writing into the skill:

- **Keep**: successful cases with high Fitness and low turnover, new low-correlation signal clusters, and unexpected failure modes.
- **Simplify**: large numbers of repeated entries from the same signal cluster should be merged into a single rule.
- **Update templates / thresholds**: if a field or template is repeatedly found to fail, return to Sections 4, 5, and 6 to update it.

### 11.4 Data Structure

- `alpha_db.json`: local alpha snapshot database containing status, metrics, expressions, and PnL. This file contains personal research history and is ignored by default by `.gitignore`; it should not be committed to a public repository.
- `SKILL.md`: final human-readable playbook; Section 12 should only keep sanitized general lessons.

## 12. Empirical Records (Auto-Updated)

> This section only preserves the mechanism. Real runs may generate alpha IDs, expressions, PnL values, submission status, and correlation records tied to a personal account and research assets. By default, these are written to the local `alpha_db.json` and not published with the repository.
> If you want to preserve general lessons, summarize them into sanitized rules and then write them back into Sections 4, 5, 6, 8, and 10.


## 12. 实证记录（自动更新）


### 2026-07-19 17:12 UTC — 批量初始化快照

- 总 alpha：1723 | ACTIVE：13 | 非 ACTIVE：1710
- 信号簇分布：{'other': 1471, 'technical': 112, 'technical+sentiment': 110, 'sentiment': 15, 'analyst': 8, 'quality/leverage': 6, 'technical+quality/leverage': 1}

**ACTIVE 高 Fitness Top 5**：
- `bl9vdZn6` (other): Sharpe=2.38, Fitness=3.16, TO=0.144 — `trade_when(pcr_oi_270 < 1, (implied_volatility_call_270 -implied_volatility_put_270), -1)`
- `WjGZ5LRN` (sentiment): Sharpe=2.08, Fitness=2.52, TO=0.138 — `ts_decay_linear(`
- `9qJdmqMV` (other): Sharpe=1.81, Fitness=2.43, TO=0.027 — `anl4_adjusted_netincome_ft`
- `2rKvWxnw` (sentiment): Sharpe=1.46, Fitness=1.71, TO=0.124 — `-ts_std_dev(scl12_buzz, 20)`
- `wpLOVaw6` (other): Sharpe=1.53, Fitness=1.60, TO=0.083 — `rank(ts_rank(operating_income/cap, 180))`

**ACTIVE 中日收益高相关对**：无 ≥ 0.7 的对（或 PnL 不足）

**明显失效信号（Fitness < 0.5，共 965 个）**：
- 簇分布：{'other': 858, 'technical+sentiment': 50, 'technical': 44, 'sentiment': 8, 'quality/leverage': 5}

**高换手（TO > 50%，共 150 个）**：
- 簇分布：{'technical+sentiment': 65, 'other': 53, 'technical': 25, 'sentiment': 7}

---

### 2026-07-19 18:49 UTC

- **9q7001vo** (ACTIVE, other): Sharpe=1.53, Fitness=1.2, TO=0.0525, DD=0.0664。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(pcr_oi_270 < 1, rank(ts_mean((implied_volatility_call_270 - implied_volatility_put_270) / implied_volatili...`
- **RR1WWM1e** (UNSUBMITTED, other): Sharpe=1.53, Fitness=1.2, TO=0.0525, DD=0.0664。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(pcr_oi_270 < 1, rank(ts_mean((implied_volatility_call_270 - implied_volatility_put_270) / implied_volatili...`
- **rKPXXYl8** (UNSUBMITTED, other): Sharpe=1.51, Fitness=1.12, TO=0.058, DD=0.0648。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(pcr_oi_270 < 1, rank(ts_mean((implied_volatility_call_270 - implied_volatility_put_270) / implied_volatili...`
- **1YzEQRGQ** (UNSUBMITTED, other): Sharpe=1.53, Fitness=1.2, TO=0.0547, DD=0.0661。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(pcr_oi_270 < 1, rank(ts_mean((implied_volatility_call_270 - implied_volatility_put_270) / implied_volatili...`
- **E5eJXM1m** (UNSUBMITTED, other): Sharpe=1.53, Fitness=1.2, TO=0.0547, DD=0.0661。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(pcr_oi_270 < 1, rank(ts_mean((implied_volatility_call_270 - implied_volatility_put_270) / implied_volatili...`
- **3qeLZJ5z** (UNSUBMITTED, other): Sharpe=1.51, Fitness=1.12, TO=0.0637, DD=0.0642。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(pcr_oi_270 < 1, rank(ts_mean((implied_volatility_call_270 - implied_volatility_put_270) / implied_volatili...`
- **QP9XLjLQ** (UNSUBMITTED, other): Sharpe=0.51, Fitness=0.31, TO=0.0434, DD=0.2065。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(pcr_oi_270 < 1, rank(ts_mean((implied_volatility_call_270 - implied_volatility_put_270) / implied_volatili...`
- **wpEgMwGY** (UNSUBMITTED, other): Sharpe=1.52, Fitness=1.13, TO=0.0605, DD=0.0646。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(pcr_oi_270 < 1, rank(ts_mean((implied_volatility_call_270 - implied_volatility_put_270) / implied_volatili...`
- **O0xaEeeJ** (UNSUBMITTED, other): Sharpe=1.53, Fitness=1.2, TO=0.0547, DD=0.0661。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(pcr_oi_270 < 1, rank(ts_mean((implied_volatility_call_270 - implied_volatility_put_270) / implied_volatili...`
- **ZYKGe591** (UNSUBMITTED, analyst): Sharpe=0.5, Fitness=0.22, TO=0.0156, DD=0.1402。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(`
- **LLdJao6a** (UNSUBMITTED, analyst): Sharpe=1.2, Fitness=0.71, TO=0.0488, DD=0.0618。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(`
- **9q7013R9** (UNSUBMITTED, analyst): Sharpe=-0.5, Fitness=-0.22, TO=0.0156, DD=0.2363。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`-rank(`
- **d5RLV1zX** (UNSUBMITTED, analyst): Sharpe=-1.2, Fitness=-0.71, TO=0.0488, DD=0.2551。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`-rank(`
- **vRvgMrQA** (UNSUBMITTED, analyst): Sharpe=-1.2, Fitness=-0.74, TO=0.0447, DD=0.2677。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`-rank(`
- **omgOpkMm** (UNSUBMITTED, other): Sharpe=1.56, Fitness=1.17, TO=0.0894, DD=0.0631。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(pcr_oi_270 < 1, rank(ts_mean((implied_volatility_call_270 - implied_volatility_put_270) / implied_volatili...`
- **qM6q1OmV** (UNSUBMITTED, other): Sharpe=-0.08, Fitness=-0.01, TO=0.2063, DD=0.0982。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(pcr_oi_270 < 1, rank(ts_delta(ts_mean(implied_volatility_call_270 - implied_volatility_put_270, 20), 10)),...`
- **2rNd0OXx** (UNSUBMITTED, other): Sharpe=-0.3, Fitness=-0.08, TO=0.1164, DD=0.0912。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(pcr_oi_270 < 1, rank(ts_mean(ts_rank(implied_volatility_call_270 - implied_volatility_put_270, 126), 20)),...`
- **88e1oLVV** (UNSUBMITTED, other): Sharpe=1.41, Fitness=0.98, TO=0.0918, DD=0.0386。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(pcr_oi_270 < 1, rank(ts_mean(implied_volatility_call_270 - implied_volatility_put_270, 20)), -1)`
- **d5RLXqNJ** (UNSUBMITTED, analyst): Sharpe=-0.49, Fitness=-0.15, TO=0.1233, DD=0.0919。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(`
- **kqZl7ROK** (UNSUBMITTED, analyst): Sharpe=-0.44, Fitness=-0.14, TO=0.118, DD=0.1096。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(`
- **WjV8qkpP** (UNSUBMITTED, analyst): Sharpe=-0.52, Fitness=-0.15, TO=0.132, DD=0.085。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(`
- **3qeLwNnP** (UNSUBMITTED, other): Sharpe=0.51, Fitness=0.07, TO=0.7397, DD=0.0551。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(pcr_oi_270 < 1, rank(ts_rank(implied_volatility_call_270 - implied_volatility_put_270, 126)), -1)`
- **akEv6RbW** (UNSUBMITTED, other): Sharpe=2.29, Fitness=1.2, TO=0.6937, DD=0.0539。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(pcr_oi_270 < 1, (implied_volatility_call_270 - implied_volatility_put_270), -1)`
- **QP9XZAw5** (UNSUBMITTED, other): Sharpe=0.57, Fitness=0.07, TO=0.7993, DD=0.0366。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when( pcr_oi_270 < 1, rank( ts_delta( ts_rank(implied_volatility_call_270-implied_volatility_put_270,126), 20 )...`
- **ZYKGPZbn** (UNSUBMITTED, other): Sharpe=-0.12, Fitness=-0.01, TO=0.3229, DD=0.1046。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(`
- **wpEgK6JY** (UNSUBMITTED, other): Sharpe=-0.21, Fitness=-0.03, TO=0.3278, DD=0.1038。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(`
- **2rNd8kOw** (UNSUBMITTED, other): Sharpe=-0.07, Fitness=-0.01, TO=0.3371, DD=0.0811。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(`
- **Xg86g9Aa** (UNSUBMITTED, other): Sharpe=1.59, Fitness=1.17, TO=0.1638, DD=0.0537。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(`
- **bldEl66q** (UNSUBMITTED, other): Sharpe=1.79, Fitness=1.24, TO=0.1756, DD=0.0392。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(`
- **1YzEYNjR** (UNSUBMITTED, other): Sharpe=1.24, Fitness=0.91, TO=0.157, DD=0.0679。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(`
- **Xg86glZb** (UNSUBMITTED, other): Sharpe=1.98, Fitness=1.31, TO=0.2444, DD=0.0427。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(`
- **pwKOwzG3** (UNSUBMITTED, other): Sharpe=1.73, Fitness=1.19, TO=0.2341, DD=0.0594。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(`
- **omgOmAZJ** (UNSUBMITTED, other): Sharpe=1.39, Fitness=0.97, TO=0.2287, DD=0.0662。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(`
- **Xg86ggOb** (UNSUBMITTED, other): Sharpe=1.88, Fitness=1.14, TO=0.2928, DD=0.0474。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(`
- **zqRpqvZo** (UNSUBMITTED, sentiment): Sharpe=1.6, Fitness=0.75, TO=0.3143, DD=0.0292。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(`
- **O0xa1Vkv** (UNSUBMITTED, sentiment): Sharpe=1.07, Fitness=0.46, TO=0.314, DD=0.0536。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(`
- **MPLmjzen** (UNSUBMITTED, analyst): Sharpe=2.91, Fitness=2.18, TO=0.1864, DD=0.034。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`0.5 * group_rank(ts_rank(operating_income / equity, 126), subindustry) + 0.5 * group_rank(ts_rank(est_eps / close, 12...`
- **WjV8E3bd** (UNSUBMITTED, sentiment): Sharpe=1.51, Fitness=0.81, TO=0.2758, DD=0.039。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(`
- **88e1mPxa** (UNSUBMITTED, analyst): Sharpe=2.24, Fitness=1.41, TO=0.2311, DD=0.0357。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(est_eps / close, 126), industry)`
- **j2rm5jWo** (UNSUBMITTED, sentiment): Sharpe=1.36, Fitness=0.75, TO=0.2551, DD=0.0461。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(`
- **d5RL2R22** (UNSUBMITTED, sentiment): Sharpe=1.49, Fitness=0.81, TO=0.267, DD=0.0407。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(`
- **JjvKVOjm** (UNSUBMITTED, sentiment): Sharpe=1.52, Fitness=0.72, TO=0.305, DD=0.0317。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(`
- **WjV8Eg9o** (UNSUBMITTED, other): Sharpe=2.01, Fitness=1.32, TO=0.063, DD=0.0295。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(operating_income / equity, 126), subindustry)`
- **YPgqjW0q** (UNSUBMITTED, sentiment): Sharpe=1.49, Fitness=0.77, TO=0.2774, DD=0.0327。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(`
- **9q70z65d** (UNSUBMITTED, sentiment): Sharpe=1.42, Fitness=0.79, TO=0.2567, DD=0.0436。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(`
- **bldEY2xq** (UNSUBMITTED, other): Sharpe=1.61, Fitness=0.7, TO=0.3589, DD=0.0536。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(`
- **N1R9XwqX** (UNSUBMITTED, other): Sharpe=0.97, Fitness=0.42, TO=0.3133, DD=0.1089。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(`
- **2rNd18PZ** (UNSUBMITTED, other): Sharpe=1.45, Fitness=0.64, TO=0.334, DD=0.0513。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(`
- **JjvZ6ePO** (UNSUBMITTED, other): Sharpe=1.7, Fitness=0.99, TO=0.2721, DD=0.0506。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(`
- **9q7LNxj2** (UNSUBMITTED, other): Sharpe=1.93, Fitness=1.07, TO=0.292, DD=0.0375。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(`
- **LLdA0MPm** (UNSUBMITTED, other): Sharpe=1.98, Fitness=1.01, TO=0.319, DD=0.0368。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(`
- **vRv3W03Q** (UNSUBMITTED, cashflow): Sharpe=1.2, Fitness=0.75, TO=0.0248, DD=0.0504。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_decay_linear(ts_scale(est_cashflow_op,252),22)-ts_decay_linear(ts_scale(est_capex,252),22)`
- **e7xoXRWd** (UNSUBMITTED, cashflow): Sharpe=1.1, Fitness=0.61, TO=0.0288, DD=0.0319。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_decay_linear(ts_scale(est_cashflow_op,252),22)-ts_decay_linear(ts_scale(est_capex,252),22)`
- **0mM01vx6** (UNSUBMITTED, cashflow): Sharpe=1.07, Fitness=0.59, TO=0.027, DD=0.0428。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_decay_linear(ts_scale(est_cashflow_op,252),22)-ts_decay_linear(ts_scale(est_capex,252),22)`
- **QP9L89qM** (UNSUBMITTED, other): Sharpe=1.35, Fitness=1.06, TO=0.0071, DD=0.068。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_regression(ts_sum(ts_backfill(fnd6_newqv1300_ivltq,60),252),ts_step(1),756,rettype = 2)`
- **Xg850n2b** (UNSUBMITTED, other): Sharpe=1.11, Fitness=0.9, TO=0.0059, DD=0.0611。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_regression(ts_sum(ts_backfill(fnd6_newqv1300_ivltq,60),252),ts_step(1),756,rettype = 2)`
- **kqZ2A30z** (UNSUBMITTED, other): Sharpe=1.34, Fitness=1.09, TO=0.0068, DD=0.0555。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_regression(ts_sum(ts_backfill(fnd6_newqv1300_ivltq,60),252),ts_step(1),756,rettype = 2)`
- **P0OdVX1J** (UNSUBMITTED, technical): Sharpe=1.57, Fitness=0.94, TO=0.6425, DD=0.1401。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`cum_rel_return = (1+ts_delay(rel_ret_all,4))*(1+ts_delay(rel_ret_all,3))*(1+ts_delay(rel_ret_all,2))*(1+ts_delay(rel_...`
- **gJ9E2KKg** (UNSUBMITTED, technical): Sharpe=1.5, Fitness=0.94, TO=0.6393, DD=0.1865。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`cum_rel_return = (1+ts_delay(rel_ret_all,4))*(1+ts_delay(rel_ret_all,3))*(1+ts_delay(rel_ret_all,2))*(1+ts_delay(rel_...`
- **bld5wV6m** (UNSUBMITTED, technical): Sharpe=1.49, Fitness=0.97, TO=0.6379, DD=0.2037。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`cum_rel_return = (1+ts_delay(rel_ret_all,4))*(1+ts_delay(rel_ret_all,3))*(1+ts_delay(rel_ret_all,2))*(1+ts_delay(rel_...`

---

