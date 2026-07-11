from datetime import datetime, timezone, timedelta


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
            closed_trades.append(trade)
        else:
            remaining_trades.append(trade)

    state["trades"] = remaining_trades
    return closed_trades


def update_circuit_breaker(state, closed_trades):
    for trade in closed_trades:
        result = trade.get("result")
        if result == "WIN":
            state["stats"]["wins"] += 1
            state["stats"]["streak"] = 0
        elif result == "LOSS":
            state["stats"]["losses"] += 1
            state["stats"]["streak"] += 1

        if state["stats"]["streak"] >= 3:
            state["circuit_breaker"] = (datetime.now(timezone.utc) + timedelta(hours=6)).isoformat()
            print("🛑 Circuit breaker activated for 6 hours!")
