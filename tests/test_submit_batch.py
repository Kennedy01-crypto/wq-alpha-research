import unittest

from scripts.submit_batch import build_active_alpha_context


class BuildActiveAlphaContextTests(unittest.TestCase):
    def test_limits_active_context_and_skips_non_pnl_entries(self) -> None:
        class DummySession:
            pass

        def fake_fetch_user_alphas(_session):
            return [
                {"id": "a1", "status": "ACTIVE"},
                {"id": "a2", "status": "ACTIVE"},
                {"id": "a3", "status": "ACTIVE"},
                {"id": "a4", "status": "ACTIVE"},
            ]

        def fake_fetch_pnl(_session, alpha_id):
            if alpha_id == "a2":
                return []
            return [0.1, 0.2, 0.3]

        result = build_active_alpha_context(
            DummySession(),
            max_active_alphas=2,
            fetch_user_alphas_fn=fake_fetch_user_alphas,
            fetch_pnl_fn=fake_fetch_pnl,
        )

        self.assertEqual([alpha["id"] for alpha in result], ["a1", "a3"])


if __name__ == "__main__":
    unittest.main()
