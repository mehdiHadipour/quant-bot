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
    """Sum of REAL remaining risk (in R) across open trades — not a flat
    1.0 per trade regardless of state. Once trailing has moved a trade's
    SL to breakeven or into guaranteed-profit territory (partial lock),
    that trade can no longer cost the portfolio anything if it's
    stopped out, so it should stop counting against the open-risk
    budget — otherwise a portfolio of several well-managed, already-
    profitable trades looks just as "risky" on paper as one where every
    trade is still at full original risk, understating actual available
    headroom for new signals.

    Uses the distance from ENTRY to the CURRENT sl (not live price), so
    this only needs data already on the trade dict — no extra price
    lookup required, and it's a deliberately conservative measure (the
    worst case if price gapped straight back to entry), not an
    optimistic one based on current unrealized P&L."""
    total = 0.0
    for trade in trades:
        if trade.get("status") != "open":
            continue
        initial_risk = float(trade.get("initial_risk", 0.0) or 0.0)
        if initial_risk <= 0:
            continue
        entry, sl, direction = trade.get("entry"), trade.get("sl"), trade.get("direction")
        if entry is None or sl is None or direction not in ("BUY", "SELL"):
            # Missing data — fail conservative (assume full original
            # risk) rather than silently undercounting.
            total += 1.0
            continue
        still_at_risk = sl < entry if direction == "BUY" else sl > entry
        if not still_at_risk:
            continue  # trailed to breakeven or better — no downside left
        total += min(abs(entry - sl) / initial_risk, 1.0)  # never over the original 1R
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


def market_group_open_count(trades, group_symbols) -> int:
    """How many currently-open trades belong to a given market group
    (e.g. the commodity group {XAUUSDT, XAGUSDT, CLUSDT, NATGASUSDT}, or
    the crypto group — everything else). Added alongside
    MAX_OPEN_PER_MARKET_GROUP/DIVERSIFICATION_ENABLED in config.py: those
    two settings were defined for the V27.13 multi-market upgrade but
    were never actually read anywhere, so a portfolio could still end up
    fully concentrated in one market group (e.g. 4 simultaneous commodity
    trades) with nothing enforcing the intended cap. This function is
    what `can_open_trade`'s new `group_symbols`/`max_open_per_group`
    parameters use to close that gap — same shape as
    `same_direction_open_count`, just grouped by market instead of by
    direction.
    """
    group = set(group_symbols)
    return sum(
        1 for t in trades
        if t.get("status") == "open" and t.get("symbol") in group
    )


def can_open_trade(state, entry, sl, tp, direction, *,
                   max_daily_loss_r, max_open_risk_r, min_reward_risk,
                   daily_loss_r=0.0, max_same_direction_open=None,
                   symbol=None, group_symbols=None, max_open_per_group=None):
    """Return (allowed, reason) with fail-closed validation.

    symbol/group_symbols/max_open_per_group are all optional and
    additive: when symbol or group_symbols is omitted, or
    max_open_per_group is None/<=0, this guard is a no-op — existing
    callers that don't pass them keep their exact previous behavior."""
    if direction not in {"BUY", "SELL"}:
        return False, "جهت معامله نامعتبر است."
    try:
        entry, sl, tp = float(entry), float(sl), float(tp)
    except (TypeError, ValueError):
        return False, "قیمت ورود/SL/TP نامعتبر است."

    # Fail closed on price geometry. This is deliberately stricter than
    # reward_risk() alone: a numerically positive RR is not enough if SL/TP
    # are on the wrong side of the entry for the declared direction. This
    # guard protects against an accidental BUY/SELL inversion upstream.
    if direction == "BUY" and not (sl < entry < tp):
        return False, "هندسهٔ قیمت برای BUY نامعتبر است؛ باید SL < Entry < TP باشد."
    if direction == "SELL" and not (tp < entry < sl):
        return False, "هندسهٔ قیمت برای SELL نامعتبر است؛ باید TP < Entry < SL باشد."

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

    # Market-group diversification cap (crypto vs. commodity/TradFi, see
    # market_group_open_count above). Symmetric no-op guard: needs all
    # three of symbol, group_symbols and a positive max_open_per_group to
    # activate, and only applies when `symbol` is itself inside the given
    # group — so passing the crypto group never blocks a commodity trade
    # and vice versa.
    if (
        symbol is not None
        and group_symbols is not None
        and max_open_per_group is not None
        and max_open_per_group > 0
        and symbol in set(group_symbols)
    ):
        group_open = market_group_open_count(state.get("trades", []), group_symbols)
        if group_open >= max_open_per_group:
            return False, (
                f"تعداد معاملات باز در همین گروه بازار از قبل به سقف "
                f"{max_open_per_group} رسیده — برای جلوگیری از تمرکز روی یک "
                f"دستهٔ دارایی (مثلاً همهٔ کالاها یا همهٔ کریپتوها با هم)."
            )

    return True, "OK"


def performance_throttle_multiplier(recent_r_multiples, *,
                                     baseline_expectancy_r,
                                     min_trades=10,
                                     lookback=20,
                                     severe_ratio=0.0,
                                     moderate_ratio=0.5):
    """Soft, informational risk throttle — separate from the hard
    circuit breaker in trade_monitor.py (which trips on 3 CONSECUTIVE
    losses and fully pauses trading).

    This looks at the last `lookback` CLOSED trades' realized expectancy
    and compares it against `baseline_expectancy_r` (what the backtest/
    research promised). A strategy can underperform its backtest for a
    long stretch without ever stringing together 3 losses in a row —
    e.g. a slow bleed of many small losses and a few break-even trades —
    which the hard circuit breaker structurally cannot catch. Returns a
    position-size multiplier in (0, 1]:

      - 1.0  : fewer than `min_trades` closed yet (not enough signal to
               judge), or recent expectancy is at/above baseline.
      - 0.5  : recent expectancy has fallen to <= `moderate_ratio` of
               baseline (default: 50% of what was promised) — trade
               smaller while the divergence is investigated.
      - 0.25 : recent expectancy has fallen to <= `severe_ratio` of
               baseline (default: 0, i.e. break-even or worse) — trade
               much smaller; this is the "something may be structurally
               wrong, not just a normal losing streak" zone.

    Pure and side-effect-free like the rest of this module: it does not
    read config or state directly, and it never blocks a trade outright
    (that stays the hard circuit breaker's job) — callers multiply their
    position size by the returned value instead.
    """
    recent = [float(x) for x in recent_r_multiples][-lookback:]
    if len(recent) < min_trades or baseline_expectancy_r <= 0:
        return 1.0

    live_expectancy = sum(recent) / len(recent)
    ratio = live_expectancy / baseline_expectancy_r

    if ratio <= severe_ratio:
        return 0.25
    if ratio <= moderate_ratio:
        return 0.5
    return 1.0
