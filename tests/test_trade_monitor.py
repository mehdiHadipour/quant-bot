import unittest
from datetime import datetime, timezone, timedelta

import trade_monitor


def fresh_state():
    return {
        "trades": [],
        "stats": {
            "wins": 0, "losses": 0, "streak": 0,
            "equity_r": 0.0, "peak_equity_r": 0.0, "max_drawdown_r": 0.0,
            "gross_profit_r": 0.0, "gross_loss_r": 0.0,
        },
        "circuit_breaker": None,
        "symbol_cooldowns": {},
    }


class TestCheckOpenTrades(unittest.TestCase):
    def test_tp_hit_closes_as_win_with_positive_r(self):
        state = fresh_state()
        state["trades"] = [{
            "symbol": "BTCUSDT", "direction": "BUY", "entry": 100, "sl": 90, "tp": 130,
            "status": "open",
        }]
        closed = trade_monitor.check_open_trades(state, current_price=131, symbol="BTCUSDT")
        self.assertEqual(len(closed), 1)
        self.assertEqual(closed[0]["result"], "WIN")
        self.assertAlmostEqual(closed[0]["r_multiple"], (131 - 100) / (100 - 90))
        self.assertEqual(state["trades"], [])  # removed from open list

    def test_sl_hit_closes_as_loss_with_negative_r(self):
        state = fresh_state()
        state["trades"] = [{
            "symbol": "ETHUSDT", "direction": "SELL", "entry": 100, "sl": 110, "tp": 70,
            "status": "open",
        }]
        closed = trade_monitor.check_open_trades(state, current_price=111, symbol="ETHUSDT")
        self.assertEqual(len(closed), 1)
        self.assertEqual(closed[0]["result"], "LOSS")
        self.assertLess(closed[0]["r_multiple"], 0)

    def test_untouched_trade_stays_open(self):
        state = fresh_state()
        state["trades"] = [{
            "symbol": "BTCUSDT", "direction": "BUY", "entry": 100, "sl": 90, "tp": 130,
            "status": "open",
        }]
        closed = trade_monitor.check_open_trades(state, current_price=105, symbol="BTCUSDT")
        self.assertEqual(closed, [])
        self.assertEqual(len(state["trades"]), 1)

    def test_other_symbol_trades_are_untouched(self):
        state = fresh_state()
        state["trades"] = [{"symbol": "ETHUSDT", "direction": "BUY", "entry": 100, "sl": 90, "tp": 130, "status": "open"}]
        closed = trade_monitor.check_open_trades(state, current_price=200, symbol="BTCUSDT")
        self.assertEqual(closed, [])
        self.assertEqual(len(state["trades"]), 1)


class TestSlWarnings(unittest.TestCase):
    def test_fires_once_then_stays_silent_for_same_trade(self):
        state = fresh_state()
        state["trades"] = [{
            "symbol": "BTCUSDT", "direction": "BUY", "entry": 100, "sl": 90, "tp": 130,
            "status": "open", "sl_warning_sent": False,
        }]
        first = trade_monitor.check_sl_warnings(state, current_price=91.5, symbol="BTCUSDT")
        self.assertEqual(len(first), 1)
        second = trade_monitor.check_sl_warnings(state, current_price=90.5, symbol="BTCUSDT")
        self.assertEqual(len(second), 0)

    def test_does_not_fire_far_from_sl(self):
        state = fresh_state()
        state["trades"] = [{
            "symbol": "BTCUSDT", "direction": "BUY", "entry": 100, "sl": 90, "tp": 130,
            "status": "open", "sl_warning_sent": False,
        }]
        warnings = trade_monitor.check_sl_warnings(state, current_price=105, symbol="BTCUSDT")
        self.assertEqual(warnings, [])


class TestCooldown(unittest.TestCase):
    def test_loss_sets_cooldown_that_blocks_then_expires(self):
        state = fresh_state()
        trade_monitor.update_circuit_breaker(state, [{"symbol": "ETHUSDT", "result": "LOSS", "r_multiple": -1.0}])
        self.assertTrue(trade_monitor.is_symbol_on_cooldown(state, "ETHUSDT"))
        self.assertFalse(trade_monitor.is_symbol_on_cooldown(state, "BTCUSDT"))

        # Simulate the cooldown having already expired.
        state["symbol_cooldowns"]["ETHUSDT"] = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
        self.assertFalse(trade_monitor.is_symbol_on_cooldown(state, "ETHUSDT"))
        self.assertNotIn("ETHUSDT", state["symbol_cooldowns"])  # cleaned up


class TestCircuitBreakerAndDashboard(unittest.TestCase):
    def test_three_losses_in_a_row_trip_circuit_breaker(self):
        state = fresh_state()
        for _ in range(3):
            trade_monitor.update_circuit_breaker(state, [{"symbol": "BTCUSDT", "result": "LOSS", "r_multiple": -1.0}])
        self.assertIsNotNone(state["circuit_breaker"])

    def test_win_resets_streak(self):
        state = fresh_state()
        trade_monitor.update_circuit_breaker(state, [{"symbol": "BTCUSDT", "result": "LOSS", "r_multiple": -1.0}])
        trade_monitor.update_circuit_breaker(state, [{"symbol": "BTCUSDT", "result": "WIN", "r_multiple": 2.0}])
        self.assertEqual(state["stats"]["streak"], 0)

    def test_equity_and_drawdown_tracking(self):
        state = fresh_state()
        trade_monitor.update_circuit_breaker(state, [{"symbol": "BTCUSDT", "result": "WIN", "r_multiple": 2.0}])
        self.assertAlmostEqual(state["stats"]["equity_r"], 2.0)
        self.assertAlmostEqual(state["stats"]["peak_equity_r"], 2.0)

        trade_monitor.update_circuit_breaker(state, [{"symbol": "BTCUSDT", "result": "LOSS", "r_multiple": -1.0}])
        self.assertAlmostEqual(state["stats"]["equity_r"], 1.0)
        self.assertAlmostEqual(state["stats"]["peak_equity_r"], 2.0)
        self.assertAlmostEqual(state["stats"]["max_drawdown_r"], 1.0)


if __name__ == "__main__":
    unittest.main()
