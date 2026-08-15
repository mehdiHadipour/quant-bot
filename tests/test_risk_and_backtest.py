import unittest
from datetime import datetime, timezone
import pandas as pd
from risk_engine import (
    reward_risk, open_risk_r, daily_closed_loss_r, can_open_trade, same_direction_open_count,
    market_group_open_count, performance_throttle_multiplier,
)
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


    def test_reject_wrong_price_geometry_for_buy(self):
        ok, reason = can_open_trade(
            {"trades": []}, 100, 110, 120, "BUY",
            max_daily_loss_r=100, max_open_risk_r=100, min_reward_risk=1.0,
        )
        self.assertFalse(ok)
        self.assertIn("هندسه", reason)

    def test_reject_wrong_price_geometry_for_sell(self):
        ok, reason = can_open_trade(
            {"trades": []}, 100, 90, 120, "SELL",
            max_daily_loss_r=100, max_open_risk_r=100, min_reward_risk=1.0,
        )
        self.assertFalse(ok)
        self.assertIn("هندسه", reason)

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

    def test_open_risk_missing_entry_sl_direction_fails_conservative(self):
        """No entry/sl/direction on the trade (e.g. malformed/legacy
        data) -> assume the full original 1R rather than silently
        undercounting portfolio risk."""
        trades = [{"status": "open", "initial_risk": 10}]
        self.assertEqual(open_risk_r(trades), 1.0)

    def test_open_risk_fresh_trade_counts_full_1r(self):
        trades = [{"status": "open", "initial_risk": 10, "entry": 100, "sl": 90, "direction": "BUY"}]
        self.assertAlmostEqual(open_risk_r(trades), 1.0)

    def test_open_risk_trailed_to_breakeven_counts_zero(self):
        """Once SL has moved to breakeven, this trade can no longer lose
        money — it should stop counting against the open-risk budget."""
        trades = [{"status": "open", "initial_risk": 10, "entry": 100, "sl": 100, "direction": "BUY"}]
        self.assertAlmostEqual(open_risk_r(trades), 0.0)

    def test_open_risk_partial_locked_counts_zero_not_negative(self):
        """SL moved PAST entry into guaranteed-profit territory — still
        zero real risk (floored, not negative)."""
        trades = [{"status": "open", "initial_risk": 10, "entry": 100, "sl": 105, "direction": "BUY"}]
        self.assertAlmostEqual(open_risk_r(trades), 0.0)

    def test_open_risk_sell_direction_symmetric(self):
        # Fresh SELL: sl above entry -> still at risk, full 1R
        fresh = [{"status": "open", "initial_risk": 10, "entry": 100, "sl": 110, "direction": "SELL"}]
        self.assertAlmostEqual(open_risk_r(fresh), 1.0)
        # Trailed to breakeven: sl == entry -> zero
        breakeven = [{"status": "open", "initial_risk": 10, "entry": 100, "sl": 100, "direction": "SELL"}]
        self.assertAlmostEqual(open_risk_r(breakeven), 0.0)

    def test_open_risk_multiple_trades_mix_of_states(self):
        trades = [
            {"status": "open", "initial_risk": 10, "entry": 100, "sl": 90, "direction": "BUY"},   # 1.0R
            {"status": "open", "initial_risk": 10, "entry": 100, "sl": 100, "direction": "BUY"},  # 0R (breakeven)
            {"status": "open", "initial_risk": 5, "entry": 50, "sl": 55, "direction": "BUY"},      # 0R (locked profit)
            {"status": "closed", "initial_risk": 10, "entry": 100, "sl": 90, "direction": "BUY"},  # ignored
        ]
        self.assertAlmostEqual(open_risk_r(trades), 1.0)

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
        allowed, _reason = can_open_trade(
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


class MarketGroupDiversificationTests(unittest.TestCase):
    """V27.13 defined MAX_OPEN_PER_MARKET_GROUP/DIVERSIFICATION_ENABLED
    in config.py but never wired them into can_open_trade — found during
    review. These tests cover the fix."""

    COMMODITIES = {"XAUUSDT", "XAGUSDT", "CLUSDT", "NATGASUSDT"}

    def test_market_group_open_count_only_counts_open_trades_in_group(self):
        trades = [
            {"status": "open", "symbol": "XAUUSDT"},
            {"status": "open", "symbol": "XAGUSDT"},
            {"status": "open", "symbol": "BTCUSDT"},  # not in group
            {"status": "closed", "symbol": "CLUSDT"},  # closed, must not count
        ]
        self.assertEqual(market_group_open_count(trades, self.COMMODITIES), 2)

    def test_group_cap_blocks_when_group_full(self):
        state = {"trades": [
            {"status": "open", "symbol": "XAUUSDT", "direction": "BUY"},
            {"status": "open", "symbol": "XAGUSDT", "direction": "BUY"},
        ]}
        allowed, reason = can_open_trade(
            state, entry=100, sl=90, tp=130, direction="BUY",
            max_daily_loss_r=100, max_open_risk_r=100, min_reward_risk=1.0,
            symbol="CLUSDT", group_symbols=self.COMMODITIES, max_open_per_group=2,
        )
        self.assertFalse(allowed)
        self.assertIn("گروه بازار", reason)

    def test_group_cap_does_not_block_symbol_outside_the_group(self):
        """A full commodity group must never block a crypto signal — the
        group_symbols/max_open_per_group guard only applies when the new
        trade's own symbol is inside the given group."""
        state = {"trades": [
            {"status": "open", "symbol": "XAUUSDT", "direction": "BUY"},
            {"status": "open", "symbol": "XAGUSDT", "direction": "BUY"},
        ]}
        allowed, _ = can_open_trade(
            state, entry=100, sl=90, tp=130, direction="BUY",
            max_daily_loss_r=100, max_open_risk_r=100, min_reward_risk=1.0,
            symbol="BTCUSDT", group_symbols=self.COMMODITIES, max_open_per_group=2,
        )
        self.assertTrue(allowed)

    def test_group_cap_no_op_when_not_passed(self):
        """Existing callers that don't pass symbol/group_symbols/
        max_open_per_group must see identical behavior to before this
        feature existed."""
        state = {"trades": [
            {"status": "open", "symbol": "XAUUSDT", "direction": "BUY"},
            {"status": "open", "symbol": "XAGUSDT", "direction": "BUY"},
            {"status": "open", "symbol": "CLUSDT", "direction": "BUY"},
        ]}
        allowed, _ = can_open_trade(
            state, entry=100, sl=90, tp=130, direction="BUY",
            max_daily_loss_r=100, max_open_risk_r=100, min_reward_risk=1.0,
        )
        self.assertTrue(allowed)

    def test_group_cap_disabled_with_zero_or_none(self):
        state = {"trades": [
            {"status": "open", "symbol": "XAUUSDT", "direction": "BUY"}
            for _ in range(10)
        ]}
        allowed, _ = can_open_trade(
            state, entry=100, sl=90, tp=130, direction="BUY",
            max_daily_loss_r=100, max_open_risk_r=100, min_reward_risk=1.0,
            symbol="XAGUSDT", group_symbols=self.COMMODITIES, max_open_per_group=0,
        )
        self.assertTrue(allowed)


class PerformanceThrottleTests(unittest.TestCase):
    def test_not_enough_trades_yet_no_throttle(self):
        self.assertEqual(
            performance_throttle_multiplier([-1, -1, -1], baseline_expectancy_r=0.15, min_trades=10),
            1.0,
        )

    def test_healthy_performance_no_throttle(self):
        recent = [0.5, -1.0, 1.5, 0.5, -1.0, 1.0, 0.5, -1.0, 1.5, 1.0]  # avg well above baseline
        self.assertEqual(
            performance_throttle_multiplier(recent, baseline_expectancy_r=0.15, min_trades=10),
            1.0,
        )

    def test_moderate_underperformance_throttles_to_half(self):
        # avg expectancy ~0.06R vs baseline 0.15R -> ratio 0.4 <= moderate_ratio 0.5
        recent = [0.06] * 10
        self.assertEqual(
            performance_throttle_multiplier(recent, baseline_expectancy_r=0.15, min_trades=10),
            0.5,
        )

    def test_severe_underperformance_throttles_to_quarter(self):
        recent = [-0.5, 0.2, -0.3, 0.1, -0.4] * 2  # avg <= 0
        self.assertEqual(
            performance_throttle_multiplier(recent, baseline_expectancy_r=0.15, min_trades=10),
            0.25,
        )

    def test_only_lookback_window_considered(self):
        """20 great trades followed by 10 terrible ones: with lookback=10
        only the terrible tail should be judged."""
        recent = [1.0] * 20 + [-1.0] * 10
        self.assertEqual(
            performance_throttle_multiplier(recent, baseline_expectancy_r=0.15, min_trades=10, lookback=10),
            0.25,
        )


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
