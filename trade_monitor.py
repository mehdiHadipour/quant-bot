from datetime import datetime, timezone, timedelta

from config import SL_WARNING_THRESHOLD, SYMBOL_COOLDOWN_CYCLES, TRAILING_TRIGGER_R, CYCLE_MINUTES
from logger import log


def check_open_trades(state, current_high, current_low, current_close, symbol):
    """Check open trades for the symbol against the latest candle's full
    price range (high/low), not just its closing price.

    Using only the close price means a brief intrabar touch of TP or SL
    that recovers before the candle closes is invisible to the bot — the
    trade would sit "open" forever even though price genuinely reached
    that level (and, on a real leveraged position, may well have been
    stopped/filled there). Checking high/low against TP/SL catches this.

    If both TP and SL fall within the same candle's range (a wide/volatile
    candle), there's no way to know which was touched first without
    tick-level data — we conservatively assume the stop was hit first,
    which never overstates performance.

    Returns a list of the fully-updated closed trade dicts.
    """
    remaining_trades = []
    closed_trades = []
    for trade in state["trades"]:
        if trade.get("status") != "open" or trade["symbol"] != symbol:
            remaining_trades.append(trade)
            continue

        if trade["direction"] == "BUY":
            hit_tp = current_high >= trade["tp"]
            hit_sl = current_low <= trade["sl"]
        else:
            hit_tp = current_low <= trade["tp"]
            hit_sl = current_high >= trade["sl"]

        if hit_sl or hit_tp:
            trade["status"] = "closed"
            if hit_sl:
                # Conservative assumption when a single candle's range
                # touched both TP and SL: treat the stop as having been
                # hit first.
                trade["result"] = "LOSS"
                trade["exit_price"] = trade["sl"]
            else:
                trade["result"] = "WIN"
                trade["exit_price"] = trade["tp"]
            trade["exit_time"] = datetime.now(timezone.utc).isoformat()

            # R-multiple: how many "risk units" (distance from entry to SL)
            # this trade made or lost, computed from the actual entry/exit/
            # sl rather than assumed from the configured multipliers, so it
            # stays correct even after a trailing-stop adjustment.
            risk_distance = abs(trade["entry"] - trade["sl"])
            if risk_distance > 0:
                if trade["direction"] == "BUY":
                    trade["r_multiple"] = (trade["exit_price"] - trade["entry"]) / risk_distance
                else:
                    trade["r_multiple"] = (trade["entry"] - trade["exit_price"]) / risk_distance
            else:
                trade["r_multiple"] = 0.0

            closed_trades.append(trade)
        else:
            remaining_trades.append(trade)

    state["trades"] = remaining_trades
    return closed_trades


def check_trailing_stop(state, current_high, current_low, symbol):
    """Move SL to breakeven (entry price) once price has progressed at
    least TRAILING_TRIGGER_R of the way from entry toward TP, checked
    against the candle's favorable extreme (high for BUY, low for SELL)
    so a brief spike toward target still triggers protection even if the
    candle closed back below/above it. Fires at most once per trade."""
    moved = []
    for trade in state.get("trades", []):
        if trade.get("status") != "open" or trade["symbol"] != symbol:
            continue
        if trade.get("sl_moved_to_breakeven"):
            continue

        entry, tp = trade["entry"], trade["tp"]
        target_distance = abs(tp - entry)
        if target_distance <= 0:
            continue

        if trade["direction"] == "BUY":
            best_price = current_high
            progress = (best_price - entry) / target_distance
        else:
            best_price = current_low
            progress = (entry - best_price) / target_distance

        if progress >= TRAILING_TRIGGER_R:
            trade["sl"] = entry
            trade["sl_moved_to_breakeven"] = True
            moved.append(trade)

    return moved


def check_sl_warnings(state, current_high, current_low, current_close, symbol):
    """Return open trades that just crossed into the 'near SL' danger zone
    for the first time (default: 80% of the way from entry to SL), checked
    against the candle's adverse extreme (low for BUY, high for SELL) so a
    brief dip toward the stop still warns even if the candle recovered by
    close. Never fires twice for the same trade."""
    warnings = []
    for trade in state.get("trades", []):
        if trade.get("status") != "open" or trade["symbol"] != symbol:
            continue
        if trade.get("sl_warning_sent"):
            continue

        entry, sl = trade["entry"], trade["sl"]
        distance = abs(entry - sl)
        if distance <= 0:
            continue

        if trade["direction"] == "BUY":
            worst_price = current_low
            progress = (entry - worst_price) / distance
        else:
            worst_price = current_high
            progress = (worst_price - entry) / distance

        if progress >= SL_WARNING_THRESHOLD:
            trade["sl_warning_sent"] = True
            warnings.append(trade)

    return warnings


def is_symbol_on_cooldown(state, symbol):
    """True if this symbol just took a loss recently and is still within
    its cooldown window (see SYMBOL_COOLDOWN_CYCLES in config.py)."""
    cooldowns = state.setdefault("symbol_cooldowns", {})
    until_str = cooldowns.get(symbol)
    if not until_str:
        return False
    until = datetime.fromisoformat(until_str)
    if datetime.now(timezone.utc) < until:
        return True
    # Cooldown has expired — clean it up so state doesn't grow forever.
    del cooldowns[symbol]
    return False


def update_circuit_breaker(state, closed_trades):
    cooldowns = state.setdefault("symbol_cooldowns", {})
    stats = state["stats"]

    for trade in closed_trades:
        result = trade.get("result")
        r = trade.get("r_multiple", 0.0)

        # --- Simple performance dashboard (R-multiple based, since the
        # bot doesn't know the person's actual position size / balance) ---
        stats["equity_r"] = stats.get("equity_r", 0.0) + r
        stats["peak_equity_r"] = max(stats.get("peak_equity_r", 0.0), stats["equity_r"])
        drawdown = stats["peak_equity_r"] - stats["equity_r"]
        stats["max_drawdown_r"] = max(stats.get("max_drawdown_r", 0.0), drawdown)
        if r > 0:
            stats["gross_profit_r"] = stats.get("gross_profit_r", 0.0) + r
        elif r < 0:
            stats["gross_loss_r"] = stats.get("gross_loss_r", 0.0) + abs(r)

        if result == "WIN":
            stats["wins"] += 1
            stats["streak"] = 0
        elif result == "LOSS":
            stats["losses"] += 1
            stats["streak"] += 1

            if SYMBOL_COOLDOWN_CYCLES > 0:
                cooldown_minutes = SYMBOL_COOLDOWN_CYCLES * CYCLE_MINUTES
                until = datetime.now(timezone.utc) + timedelta(minutes=cooldown_minutes)
                cooldowns[trade["symbol"]] = until.isoformat()
                log.info(f"🧊 {trade['symbol']} تا {until.isoformat()} در حالت Cooldown قرار گرفت.")

        if stats["streak"] >= 3:
            state["circuit_breaker"] = (datetime.now(timezone.utc) + timedelta(hours=6)).isoformat()
            log.warning("🛑 Circuit breaker activated for 6 hours!")
