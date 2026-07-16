from datetime import datetime, timezone, timedelta

from config import SL_WARNING_THRESHOLD, SYMBOL_COOLDOWN_CYCLES
from logger import log


def check_open_trades(state, current_price, symbol):
    """Check open trades for the symbol against the current price.

    Returns a list of the fully-updated closed trade dicts (not just
    "WIN"/"LOSS" labels), so callers can log them to history without
    re-deriving them from state after it's already been mutated.
    """
    remaining_trades = []
    closed_trades = []
    for trade in state["trades"]:
        if trade.get("status") != "open" or trade["symbol"] != symbol:
            remaining_trades.append(trade)
            continue

        hit_tp = (trade["direction"] == "BUY" and current_price >= trade["tp"]) or \
                  (trade["direction"] == "SELL" and current_price <= trade["tp"])
        hit_sl = (trade["direction"] == "BUY" and current_price <= trade["sl"]) or \
                  (trade["direction"] == "SELL" and current_price >= trade["sl"])

        if hit_tp or hit_sl:
            trade["status"] = "closed"
            trade["result"] = "WIN" if hit_tp else "LOSS"
            trade["exit_price"] = current_price
            trade["exit_time"] = datetime.now(timezone.utc).isoformat()

            # R-multiple: how many "risk units" (distance from entry to SL)
            # this trade made or lost. A trade that hits its ATR-based TP
            # is always the same R (since SL/TP are fixed at entry), but
            # computing it from the actual entry/exit/sl is more honest
            # than assuming a fixed ratio, and stays correct even if those
            # multipliers are changed later via config.
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


def check_sl_warnings(state, current_price, symbol):
    """Return open trades that just crossed into the 'near SL' danger zone
    for the first time (default: 80% of the way from entry to SL), so the
    caller can send a one-time warning before the stop actually triggers.
    Never fires twice for the same trade thanks to the sl_warning_sent flag."""
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
            progress = (entry - current_price) / distance
        else:
            progress = (current_price - entry) / distance

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
                cooldown_minutes = SYMBOL_COOLDOWN_CYCLES * 15
                until = datetime.now(timezone.utc) + timedelta(minutes=cooldown_minutes)
                cooldowns[trade["symbol"]] = until.isoformat()
                log.info(f"🧊 {trade['symbol']} تا {until.isoformat()} در حالت Cooldown قرار گرفت.")

        if stats["streak"] >= 3:
            state["circuit_breaker"] = (datetime.now(timezone.utc) + timedelta(hours=6)).isoformat()
            log.warning("🛑 Circuit breaker activated for 6 hours!")
