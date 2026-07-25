import unittest
from datetime import datetime, timezone
import pandas as pd
from risk_engine import reward_risk, open_risk_r, daily_closed_loss_r, can_open_trade, same_direction_open_count
from backtest import BacktestTrade, simulate_trade


class RiskEngineTests(unittest.TestCase):
    def test_reward_risk_buy_sell(self):
        self.assertAlmostEqual(reward_risk(100, 90, 120, "BUY"), 2.0)
        self.assertAlmostEqual(reward_risk(100, 110, 80, "SELL"), 2.0)

    def test_reject_bad_rr(self):
        ok, reason = can_open_trade(
            {"trades": []}, 100, 90, 105, "BUY",
            max_daily_loss_r=3, max_open_risk_r=4,
            min_reward_risk=1.5, daily_loss_r=0
        )
        self.assertFalse(ok)
        self.assertIn("نسبت", reason)

    def test_reject_daily_loss_limit(self):
        ok, _ = can_open_trade(
            {"trades": []}, 100, 90, 120, "BUY",
            max_daily_loss_r=3, max_open_risk_r=4,
            min_reward_risk=1.5, daily_loss_r=3
        )
        self.assertFalse(ok)

    def test_open_risk_counts_only_open(self):
        trades = [
            {"status": "open", "initial_risk": 10},
            {"status": "closed", "initial_risk": 10},
        ]
        self.assertEqual(open_risk_r(trades), 1.0)

    def test_daily_loss(self):
        today = datetime.now(timezone.utc).isoformat()
        df = pd.DataFrame([
            {"exit_time": today, "r_multiple": -1.2},
            {"exit_time": today, "r_multiple": 0.5},
        ])
        self.assertAlmostEqual(daily_closed_loss_r(df), 1.2)

    def test_same_direction_open_count_ignores_closed_and_other_direction(self):
        trades = [
            {"status": "open", "direction": "SELL"},
            {"status": "open", "direction": "SELL"},
            {"status": "open", "direction": "BUY"},
            {"status": "closed", "direction": "SELL"},  # closed, must not count
        ]
        self.assertEqual(same_direction_open_count(trades, "SELL"), 2)
        self.assertEqual(same_direction_open_count(trades, "BUY"), 1)

    def test_reject_concentrated_same_direction_exposure(self):
        """3 correlated coins already SELL open + limit of 3 -> a 4th SELL
        signal must be rejected even though max_open_risk_r has room."""
        state = {"trades": [
            {"status": "open", "direction": "SELL", "initial_risk": 1.0},
            {"status": "open", "direction": "SELL", "initial_risk": 1.0},
            {"status": "open", "direction": "SELL", "initial_risk": 1.0},
        ]}
        allowed, reason = can_open_trade(
            state, entry=100, sl=110, tp=70, direction="SELL",
            max_daily_loss_r=100, max_open_risk_r=100, min_reward_risk=1.0,
            max_same_direction_open=3,
        )
        self.assertFalse(allowed)
        self.assertIn("هم‌جهت", reason)

    def test_opposite_direction_not_blocked_by_same_direction_guard(self):
        """The guard is direction-specific: 3 open SELLs shouldn't block a
        new BUY signal."""
        state = {"trades": [
            {"status": "open", "direction": "SELL", "initial_risk": 1.0},
            {"status": "open", "direction": "SELL", "initial_risk": 1.0},
            {"status": "open", "direction": "SELL", "initial_risk": 1.0},
        ]}
        allowed, reason = can_open_trade(
            state, entry=100, sl=90, tp=130, direction="BUY",
            max_daily_loss_r=100, max_open_risk_r=100, min_reward_risk=1.0,
            max_same_direction_open=3,
        )
        self.assertTrue(allowed)

    def test_same_direction_guard_disabled_when_zero_or_none(self):
        state = {"trades": [
            {"status": "open", "direction": "SELL", "initial_risk": 1.0}
            for _ in range(10)
        ]}
        allowed, _ = can_open_trade(
            state, entry=100, sl=110, tp=70, direction="SELL",
            max_daily_loss_r=100, max_open_risk_r=100, min_reward_risk=1.0,
            max_same_direction_open=0,
        )
        self.assertTrue(allowed)
        allowed2, _ = can_open_trade(
            state, entry=100, sl=110, tp=70, direction="SELL",
            max_daily_loss_r=100, max_open_risk_r=100, min_reward_risk=1.0,
        )
        self.assertTrue(allowed2)


class BacktestTests(unittest.TestCase):
    def test_conservative_same_candle_prefers_sl(self):
        trade = BacktestTrade(100, 95, 110, "BUY", 0)
        result = simulate_trade([{"high": 111, "low": 94}], trade)
        self.assertEqual(result.result, "LOSS")
        self.assertEqual(result.r_multiple, -1.0)

    def test_sell_tp(self):
        trade = BacktestTrade(100, 105, 90, "SELL", 0)
        result = simulate_trade([{"high": 102, "low": 89}], trade)
        self.assertEqual(result.result, "WIN")
        self.assertEqual(result.r_multiple, 2.0)


if __name__ == "__main__":
    unittest.main()
