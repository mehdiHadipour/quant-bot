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
        # Candle range 129-132 -> high crosses tp(130)
        closed = trade_monitor.check_open_trades(state, current_high=132, current_low=129, current_close=131, symbol="BTCUSDT")
        self.assertEqual(len(closed), 1)
        self.assertEqual(closed[0]["result"], "WIN")
        self.assertEqual(closed[0]["exit_price"], 130)  # exits at the TP level, not the candle close
        self.assertAlmostEqual(closed[0]["r_multiple"], (130 - 100) / (100 - 90))
        self.assertEqual(state["trades"], [])  # removed from open list

    def test_sl_hit_closes_as_loss_with_negative_r(self):
        state = fresh_state()
        state["trades"] = [{
            "symbol": "ETHUSDT", "direction": "SELL", "entry": 100, "sl": 110, "tp": 70,
            "status": "open",
        }]
        closed = trade_monitor.check_open_trades(state, current_high=112, current_low=108, current_close=109, symbol="ETHUSDT")
        self.assertEqual(len(closed), 1)
        self.assertEqual(closed[0]["result"], "LOSS")
        self.assertEqual(closed[0]["exit_price"], 110)
        self.assertLess(closed[0]["r_multiple"], 0)

    def test_untouched_trade_stays_open(self):
        state = fresh_state()
        state["trades"] = [{
            "symbol": "BTCUSDT", "direction": "BUY", "entry": 100, "sl": 90, "tp": 130,
            "status": "open",
        }]
        closed = trade_monitor.check_open_trades(state, current_high=107, current_low=103, current_close=105, symbol="BTCUSDT")
        self.assertEqual(closed, [])
        self.assertEqual(len(state["trades"]), 1)

    def test_other_symbol_trades_are_untouched(self):
        state = fresh_state()
        state["trades"] = [{"symbol": "ETHUSDT", "direction": "BUY", "entry": 100, "sl": 90, "tp": 130, "status": "open"}]
        closed = trade_monitor.check_open_trades(state, current_high=205, current_low=195, current_close=200, symbol="BTCUSDT")
        self.assertEqual(closed, [])
        self.assertEqual(len(state["trades"]), 1)

    def test_intrabar_sl_touch_detected_even_if_candle_closes_back_inside_range(self):
        """This is the exact real-world bug that was reported: a trade
        touches SL briefly within a candle, then price recovers and the
        candle CLOSES back inside the original range. A close-price-only
        check would never see this and would leave the trade open forever
        (no closing message ever sent). Checking the candle's low/high
        catches it."""
        state = fresh_state()
        state["trades"] = [{
            "symbol": "BTCUSDT", "direction": "BUY", "entry": 100, "sl": 90, "tp": 130,
            "status": "open",
        }]
        # Candle wicked down to 88 (through SL=90) then recovered and
        # CLOSED at 95 — well inside the open range, nowhere near SL/TP.
        closed = trade_monitor.check_open_trades(state, current_high=101, current_low=88, current_close=95, symbol="BTCUSDT")
        self.assertEqual(len(closed), 1, "a low that wicked through SL must be detected even though the close recovered")
        self.assertEqual(closed[0]["result"], "LOSS")
        self.assertEqual(closed[0]["exit_price"], 90)

    def test_both_tp_and_sl_in_same_candle_conservatively_assumes_sl_first(self):
        state = fresh_state()
        state["trades"] = [{
            "symbol": "BTCUSDT", "direction": "BUY", "entry": 100, "sl": 90, "tp": 130,
            "status": "open",
        }]
        # A single wide/volatile candle whose range covers both TP and SL.
        closed = trade_monitor.check_open_trades(state, current_high=135, current_low=85, current_close=110, symbol="BTCUSDT")
        self.assertEqual(len(closed), 1)
        self.assertEqual(closed[0]["result"], "LOSS")  # conservative assumption


class TestTrailingStop(unittest.TestCase):
    def test_v25_12_partial_lock_at_75_percent_locks_real_profit(self):
        """New second stage: once price is 75% of the way to TP (with
        initial_risk stored), SL moves to lock in 0.5R of REAL profit,
        not just breakeven."""
        state = fresh_state()
        state["trades"] = [{
            "symbol": "BTCUSDT", "direction": "BUY", "entry": 100, "sl": 90, "tp": 130,
            "status": "open", "sl_moved_to_breakeven": False, "sl_partial_lock_done": False,
            "initial_risk": 10,  # abs(entry - original sl)
        }]
        # 75% from 100 to 130 is 122.5.
        moved = trade_monitor.check_trailing_stop(state, current_high=123, current_low=118, symbol="BTCUSDT")
        self.assertEqual(len(moved), 1)
        self.assertEqual(moved[0]["stage"], "partial_lock")
        # New SL = entry + 0.5 * initial_risk = 100 + 5 = 105 (locks +0.5R)
        self.assertEqual(state["trades"][0]["sl"], 105)
        self.assertTrue(state["trades"][0]["sl_partial_lock_done"])
        self.assertTrue(state["trades"][0]["sl_moved_to_breakeven"])

    def test_v25_12_candle_jumping_straight_past_both_thresholds_locks_partial_directly(self):
        """A single big candle that jumps straight past 75% should go
        directly to partial_lock, not pause at breakeven first."""
        state = fresh_state()
        state["trades"] = [{
            "symbol": "BTCUSDT", "direction": "BUY", "entry": 100, "sl": 90, "tp": 130,
            "status": "open", "sl_moved_to_breakeven": False, "sl_partial_lock_done": False,
            "initial_risk": 10,
        }]
        moved = trade_monitor.check_trailing_stop(state, current_high=128, current_low=126, symbol="BTCUSDT")
        self.assertEqual(len(moved), 1)
        self.assertEqual(moved[0]["stage"], "partial_lock")
        self.assertEqual(state["trades"][0]["sl"], 105)

    def test_v25_12_progressive_two_cycle_trail_breakeven_then_partial_lock(self):
        """Across two separate cycles: first reaches breakeven, then a
        later cycle reaches the partial-lock threshold."""
        state = fresh_state()
        state["trades"] = [{
            "symbol": "BTCUSDT", "direction": "BUY", "entry": 100, "sl": 90, "tp": 130,
            "status": "open", "sl_moved_to_breakeven": False, "sl_partial_lock_done": False,
            "initial_risk": 10,
        }]
        first = trade_monitor.check_trailing_stop(state, current_high=116, current_low=112, symbol="BTCUSDT")
        self.assertEqual(first[0]["stage"], "breakeven")
        self.assertEqual(state["trades"][0]["sl"], 100)

        second = trade_monitor.check_trailing_stop(state, current_high=124, current_low=120, symbol="BTCUSDT")
        self.assertEqual(second[0]["stage"], "partial_lock")
        self.assertEqual(state["trades"][0]["sl"], 105)

    def test_v25_12_sell_direction_partial_lock_locks_correctly(self):
        """Same as above but for a SELL trade — SL should move BELOW
        entry (in profit direction for a short) by 0.5R."""
        state = fresh_state()
        state["trades"] = [{
            "symbol": "BTCUSDT", "direction": "SELL", "entry": 100, "sl": 110, "tp": 70,
            "status": "open", "sl_moved_to_breakeven": False, "sl_partial_lock_done": False,
            "initial_risk": 10,
        }]
        # 75% from 100 down to 70 is 77.5.
        moved = trade_monitor.check_trailing_stop(state, current_high=82, current_low=76, symbol="BTCUSDT")
        self.assertEqual(moved[0]["stage"], "partial_lock")
        # New SL = entry - 0.5 * initial_risk = 100 - 5 = 95
        self.assertEqual(state["trades"][0]["sl"], 95)

    def test_v25_12_legacy_trade_without_initial_risk_only_ever_gets_breakeven(self):
        """A trade opened before v25.6 (no "initial_risk" field) should
        gracefully never reach stage 2 — it still gets stage 1
        (breakeven) exactly as before, and stops there."""
        state = fresh_state()
        state["trades"] = [{
            "symbol": "BTCUSDT", "direction": "BUY", "entry": 100, "sl": 90, "tp": 130,
            "status": "open", "sl_moved_to_breakeven": False,
            # no "initial_risk" key at all
        }]
        moved = trade_monitor.check_trailing_stop(state, current_high=128, current_low=126, symbol="BTCUSDT")
        self.assertEqual(len(moved), 1)
        self.assertEqual(moved[0]["stage"], "breakeven")
        self.assertEqual(state["trades"][0]["sl"], 100)  # breakeven only, never partial_lock

    def test_v25_12_win_after_partial_lock_still_credits_full_original_r(self):
        """Partial-lock must not corrupt the eventual win's R-multiple —
        a trade that reaches partial_lock and THEN goes on to hit full
        TP should still be credited the full original R, same guarantee
        as the v25.6 fix for plain breakeven."""
        state = fresh_state()
        state["trades"] = [{
            "symbol": "BTCUSDT", "direction": "BUY", "entry": 100, "sl": 90, "tp": 130,
            "status": "open", "sl_moved_to_breakeven": False, "sl_partial_lock_done": False,
            "initial_risk": 10,
        }]
        trade_monitor.check_trailing_stop(state, current_high=124, current_low=120, symbol="BTCUSDT")
        self.assertEqual(state["trades"][0]["sl"], 105)  # partial-locked

        closed = trade_monitor.check_open_trades(state, current_high=132, current_low=129, current_close=131, symbol="BTCUSDT")
        self.assertEqual(len(closed), 1)
        self.assertEqual(closed[0]["result"], "WIN")
        self.assertAlmostEqual(closed[0]["r_multiple"], 3.0, places=3)  # (130-100)/10, unaffected by the moved sl

    def test_moves_sl_to_entry_once_halfway_to_tp(self):
        state = fresh_state()
        state["trades"] = [{
            "symbol": "BTCUSDT", "direction": "BUY", "entry": 100, "sl": 90, "tp": 130,
            "status": "open", "sl_moved_to_breakeven": False,
        }]
        # Halfway from 100 to 130 is 115; candle high reached it.
        moved = trade_monitor.check_trailing_stop(state, current_high=115, current_low=112, symbol="BTCUSDT")
        self.assertEqual(len(moved), 1)
        self.assertEqual(state["trades"][0]["sl"], 100)
        self.assertTrue(state["trades"][0]["sl_moved_to_breakeven"])

    def test_does_not_fire_before_halfway(self):
        state = fresh_state()
        state["trades"] = [{
            "symbol": "BTCUSDT", "direction": "BUY", "entry": 100, "sl": 90, "tp": 130,
            "status": "open", "sl_moved_to_breakeven": False,
        }]
        moved = trade_monitor.check_trailing_stop(state, current_high=105, current_low=102, symbol="BTCUSDT")
        self.assertEqual(moved, [])
        self.assertEqual(state["trades"][0]["sl"], 90)  # unchanged

    def test_fires_once_then_stays_silent(self):
        state = fresh_state()
        state["trades"] = [{
            "symbol": "BTCUSDT", "direction": "BUY", "entry": 100, "sl": 90, "tp": 130,
            "status": "open", "sl_moved_to_breakeven": False,
        }]
        trade_monitor.check_trailing_stop(state, current_high=115, current_low=112, symbol="BTCUSDT")
        second = trade_monitor.check_trailing_stop(state, current_high=125, current_low=120, symbol="BTCUSDT")
        self.assertEqual(second, [])  # already moved once, doesn't fire again

    def test_intrabar_spike_to_halfway_triggers_even_if_close_pulls_back(self):
        """Trailing should trigger on a brief intrabar spike toward target,
        not require the candle to CLOSE at/beyond the trigger level."""
        state = fresh_state()
        state["trades"] = [{
            "symbol": "BTCUSDT", "direction": "BUY", "entry": 100, "sl": 90, "tp": 130,
            "status": "open", "sl_moved_to_breakeven": False,
        }]
        # High spiked to 116 (past the 115 halfway point) but pulled back low.
        moved = trade_monitor.check_trailing_stop(state, current_high=116, current_low=103, symbol="BTCUSDT")
        self.assertEqual(len(moved), 1)
        self.assertEqual(state["trades"][0]["sl"], 100)

    def test_reported_scenario_reaches_halfway_then_fully_reverses_closes_at_breakeven_not_full_loss(self):
        """Directly reproduces the exact pattern that was reported: price
        gets about halfway to TP, then fully reverses. Before this fix,
        the trade would close at the full, far-away original SL for a
        real -1.0R loss. After this fix, SL has already been moved to
        entry by the time the reversal happens, so the trade closes at
        breakeven (r_multiple 0.0, since risk distance from the *current*
        SL is now zero) instead of a full loss."""
        state = fresh_state()
        state["trades"] = [{
            "symbol": "BTCUSDT", "direction": "BUY", "entry": 100, "sl": 90, "tp": 130,
            "status": "open", "sl_moved_to_breakeven": False,
        }]

        # Cycle 1: price reaches halfway (115) -> SL trails to breakeven (100)
        trade_monitor.check_trailing_stop(state, current_high=115, current_low=112, symbol="BTCUSDT")
        self.assertEqual(state["trades"][0]["sl"], 100)

        # Cycle 2: price fully reverses back down through the entry level
        trade_monitor.check_trailing_stop(state, current_high=99, current_low=97, symbol="BTCUSDT")  # already moved, no-op
        closed = trade_monitor.check_open_trades(state, current_high=100, current_low=97, current_close=98, symbol="BTCUSDT")

        self.assertEqual(len(closed), 1)
        self.assertEqual(closed[0]["result"], "LOSS")  # technically below entry…
        self.assertAlmostEqual(closed[0]["r_multiple"], 0.0, places=3)  # …but ~breakeven, not -1.0R
        # Without this fix, the original SL (90) would still be active and
        # this same reversal would have closed at a full -1.0R loss.

    def test_v25_6_win_after_trailing_credits_full_original_r_not_zero(self):
        """The actual bug reported live: because TRAILING_TRIGGER_R (0.5)
        is always reached before TP (1.0), a trade's SL has *already* been
        moved to breakeven by the time it goes on to hit full TP. Before
        v25.6, r_multiple was recomputed from the CURRENT sl (now ==
        entry), making risk_distance 0 and silently recording every such
        win as 0.0R instead of its real reward — exactly matching a
        reported "60% win rate but flat/negative equity" mismatch. With
        "initial_risk" frozen at trade-open time, the win is now credited
        correctly even after trailing has moved the live sl field."""
        state = fresh_state()
        state["trades"] = [{
            "symbol": "BTCUSDT", "direction": "BUY", "entry": 100, "sl": 90, "tp": 130,
            "status": "open", "sl_moved_to_breakeven": False,
            "initial_risk": 10,  # abs(entry - original sl), as main.py now stores at open
        }]

        # Cycle 1: price reaches halfway -> SL trails to breakeven, but
        # initial_risk must NOT change.
        trade_monitor.check_trailing_stop(state, current_high=115, current_low=112, symbol="BTCUSDT")
        self.assertEqual(state["trades"][0]["sl"], 100)
        self.assertEqual(state["trades"][0]["initial_risk"], 10)

        # Cycle 2: price goes on to hit full TP.
        closed = trade_monitor.check_open_trades(state, current_high=132, current_low=129, current_close=131, symbol="BTCUSDT")

        self.assertEqual(len(closed), 1)
        self.assertEqual(closed[0]["result"], "WIN")
        self.assertAlmostEqual(closed[0]["r_multiple"], 3.0, places=3)  # (130-100)/10, NOT 0.0


class TestSlWarnings(unittest.TestCase):
    def test_fires_once_then_stays_silent_for_same_trade(self):
        state = fresh_state()
        state["trades"] = [{
            "symbol": "BTCUSDT", "direction": "BUY", "entry": 100, "sl": 90, "tp": 130,
            "status": "open", "sl_warning_sent": False,
        }]
        first = trade_monitor.check_sl_warnings(state, current_high=93, current_low=91.5, current_close=92, symbol="BTCUSDT")
        self.assertEqual(len(first), 1)
        second = trade_monitor.check_sl_warnings(state, current_high=91, current_low=90.5, current_close=90.8, symbol="BTCUSDT")
        self.assertEqual(len(second), 0)

    def test_does_not_fire_far_from_sl(self):
        state = fresh_state()
        state["trades"] = [{
            "symbol": "BTCUSDT", "direction": "BUY", "entry": 100, "sl": 90, "tp": 130,
            "status": "open", "sl_warning_sent": False,
        }]
        warnings = trade_monitor.check_sl_warnings(state, current_high=107, current_low=104, current_close=105, symbol="BTCUSDT")
        self.assertEqual(warnings, [])

    def test_intrabar_dip_toward_sl_triggers_even_if_close_recovers(self):
        state = fresh_state()
        state["trades"] = [{
            "symbol": "BTCUSDT", "direction": "BUY", "entry": 100, "sl": 90, "tp": 130,
            "status": "open", "sl_warning_sent": False,
        }]
        # Low wicked to 91.5 (80%+ of the way to SL=90) but closed back at 98.
        warnings = trade_monitor.check_sl_warnings(state, current_high=99, current_low=91.5, current_close=98, symbol="BTCUSDT")
        self.assertEqual(len(warnings), 1)


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
