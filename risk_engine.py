"""Pure, side-effect-free portfolio risk guards for Quant Bot.

The engine works in R units (one R = the original stop distance of a trade).
This deliberately avoids pretending to know the user's account balance.
It is designed to be easy to unit-test and safe to call before opening a trade.
"""
from datetime import datetime, timezone


def reward_risk(entry: float, sl: float, tp: float, direction: str) -> float:
    risk = abs(entry - sl)
    if risk <= 0:
        return 0.0
    reward = (tp - entry) if direction == "BUY" else (entry - tp)
    return reward / risk


def open_risk_r(trades) -> float:
    total = 0.0
    for trade in trades:
        if trade.get("status") != "open":
            continue
        initial_risk = float(trade.get("initial_risk", 0.0) or 0.0)
        if initial_risk > 0:
            total += 1.0
    return total


def daily_closed_loss_r(history_df, now=None) -> float:
    """Sum only negative R results closed on the current UTC date."""
    if history_df is None or history_df.empty:
        return 0.0
    now = now or datetime.now(timezone.utc)
    today = now.date().isoformat()
    if "exit_time" not in history_df.columns or "r_multiple" not in history_df.columns:
        return 0.0
    exits = history_df["exit_time"].astype(str)
    rs = history_df["r_multiple"]
    total = 0.0
    for exit_time, r in zip(exits, rs):
        try:
            dt = datetime.fromisoformat(exit_time.replace("Z", "+00:00"))
            if dt.date().isoformat() == today and float(r) < 0:
                total += abs(float(r))
        except (ValueError, TypeError):
            continue
    return total


def same_direction_open_count(trades, direction) -> int:
    """How many currently-open trades share this direction. Used to guard
    against concentrated directional risk dressed up as "diversification"
    — e.g. BTC+ETH+SUI+SOL all SELL at once isn't 4 independent bets,
    it's one leveraged bet on "crypto down" across 4 tickets, since crypto
    assets are typically highly correlated."""
    return sum(
        1 for t in trades
        if t.get("status") == "open" and t.get("direction") == direction
    )


def can_open_trade(state, entry, sl, tp, direction, *,
                   max_daily_loss_r, max_open_risk_r, min_reward_risk,
                   daily_loss_r=0.0, max_same_direction_open=None):
    """Return (allowed, reason) with fail-closed validation."""
    if direction not in {"BUY", "SELL"}:
        return False, "جهت معامله نامعتبر است."
    try:
        entry, sl, tp = float(entry), float(sl), float(tp)
    except (TypeError, ValueError):
        return False, "قیمت ورود/SL/TP نامعتبر است."

    rr = reward_risk(entry, sl, tp, direction)
    if rr < min_reward_risk:
        return False, f"نسبت سود به ریسک {rr:.2f}R کمتر از حداقل {min_reward_risk:.2f}R است."

    if max_daily_loss_r > 0 and daily_loss_r >= max_daily_loss_r:
        return False, f"سقف زیان روزانه ({max_daily_loss_r:.2f}R) فعال شده است."

    current_open_risk = open_risk_r(state.get("trades", []))
    if max_open_risk_r > 0 and current_open_risk + 1.0 > max_open_risk_r:
        return False, f"ریسک باز پرتفوی ({current_open_risk:.2f}R) به سقف {max_open_risk_r:.2f}R می‌رسد."

    if max_same_direction_open is not None and max_same_direction_open > 0:
        same_dir = same_direction_open_count(state.get("trades", []), direction)
        if same_dir >= max_same_direction_open:
            return False, (
                f"تعداد معاملات باز هم‌جهت ({direction}) از قبل به سقف "
                f"{max_same_direction_open} رسیده — ریسک تمرکز جهت‌دار "
                f"(نه تنوع واقعی، چون کریپتو معمولاً هم‌جهت حرکت می‌کند)."
            )

    return True, "OK"
