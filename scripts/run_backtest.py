"""
Walk-forward PORTFOLIO backtest: replays historical data for ALL
symbols together on ONE shared timeline through the SAME production
functions the live bot uses every cycle — indicators.analyze_market,
trade_monitor.{is_symbol_on_cooldown, check_trailing_stop,
check_open_trades, update_circuit_breaker}, and risk_engine.can_open_trade
— so backtest behavior can't silently drift from live behavior.

v2 (this version) fixes the biggest gap in v1: symbols used to be
backtested independently, one at a time, each with its own private
state — so MAX_CONCURRENT_TRADES and MAX_SAME_DIRECTION_OPEN were only
ever enforced trivially (max 1 trade per symbol against itself), never
across the real shared portfolio, and MAX_DAILY_LOSS_R was hardcoded to
0.0 (never enforced at all). Now every symbol shares ONE state dict, one
timeline, and real daily-loss tracking — matching how the live bot
actually manages risk across all symbols together.

REQUIRES: run scripts/fetch_historical_klines.py first, for every
symbol you want included.

USAGE:
    python scripts/run_backtest.py --symbols BTCUSDT,ETHUSDT,SOLUSDT

KNOWN SIMPLIFICATIONS (read before trusting the numbers):
  - Funding rate is not replayed (no historical funding data fetched),
    so funding_score is always 0 here, same as when it's simply
    unavailable live — never blocks a signal either way.
  - Cooldown/circuit-breaker timing is evaluated once per 1H candle (the
    bot's primary decision timeframe), not the live bot's exact
    10-minute wake-up cadence — can shift a cooldown's expiry by up to
    one 1H-candle-boundary versus live.
  - Within a single shared timestamp, symbols are processed in the order
    given on --symbols. If two symbols would both want the last
    available MAX_CONCURRENT_TRADES slot at the exact same hour, whichever
    is listed first wins — a minor, disclosed ordering artifact, not a
    live-vs-backtest behavior difference (main.py's SYMBOLS list also has
    a fixed order for the same reason).
  - This was logic-tested (pagination, no-lookahead slicing, historical-
    time replay for cooldowns, full open->trail->close->cooldown
    lifecycle, and this version's cross-symbol portfolio gates) against
    synthetic data in a sandboxed review environment with no network
    access to real market data. Sanity-check the first run's trade count
    and date range before trusting the results.
"""
import argparse
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd

from indicators import analyze_market
from trade_monitor import (
    is_symbol_on_cooldown, check_trailing_stop, check_open_trades, update_circuit_breaker,
)
from risk_engine import can_open_trade
from research import summarize_r_multiples
import config

WARMUP_CANDLES = 250  # 1H-candle-index warmup for the fast timeframes' own indicators
ROLLING_WINDOW = 300  # matches the live bot's typical fetch size


def has_reached_max_concurrent_trades(state):
    """Ported directly from main.py's identically-named function (kept
    here rather than imported, since main.py can't be imported standalone
    without pulling in its Telegram/git side effects) — same logic,
    same MAX_CONCURRENT_TRADES=0 disables it."""
    if config.MAX_CONCURRENT_TRADES <= 0:
        return False
    open_count = sum(1 for t in state["trades"] if t.get("status") == "open")
    return open_count >= config.MAX_CONCURRENT_TRADES


def load_symbol_frames(symbol, data_dir, intervals=("15m", "1h", "4h", "1d")):
    frames = {}
    for interval in intervals:
        path = os.path.join(data_dir, f"{symbol}_{interval}.csv")
        if not os.path.exists(path):
            raise FileNotFoundError(
                f"Missing {path} — run: python scripts/fetch_historical_klines.py "
                f"--symbols {symbol} first."
            )
        df = pd.read_csv(path)
        if "close_time" not in df.columns:
            raise ValueError(f"{path} has no close_time column — re-download with fetch_historical_klines.py")
        frames[interval] = df.sort_values("close_time").reset_index(drop=True)
    return frames


def slice_as_of(df, as_of_close_time):
    """Every candle whose close_time <= as_of_close_time — the core
    no-lookahead guarantee. Capped to the same rolling window size the
    live bot uses so indicator behavior matches."""
    sliced = df[df["close_time"] <= as_of_close_time]
    return sliced.tail(ROLLING_WINDOW).reset_index(drop=True)


def fresh_portfolio_state():
    return {
        "trades": [],
        "stats": {"wins": 0, "losses": 0, "streak": 0, "equity_r": 0.0,
                   "peak_equity_r": 0.0, "max_drawdown_r": 0.0,
                   "gross_profit_r": 0.0, "gross_loss_r": 0.0},
        "circuit_breaker": None,
        "symbol_cooldowns": {},
    }


def todays_realized_loss_r(closed_trades, as_of_dt):
    """Sum of negative R across ALL symbols' trades closed on the same
    UTC calendar date as as_of_dt — the portfolio-wide equivalent of
    main.py's current_daily_loss_r(), computed from the in-memory closed
    trade list instead of history.csv (nothing has been written to disk
    mid-backtest)."""
    today = as_of_dt.date()
    total = 0.0
    for t in closed_trades:
        try:
            exit_dt = datetime.fromisoformat(t["exit_time"])
        except (KeyError, ValueError, TypeError):
            continue
        r = t.get("r_multiple", 0.0)
        if exit_dt.date() == today and r < 0:
            total += abs(r)
    return total


def run_portfolio_backtest(symbols, data_dir, verbose=False, max_abs_structure_score=None):
    """max_abs_structure_score: EXPERIMENTAL, backtest-only filter (not
    wired into the live bot). Tests a hypothesis found by analyzing a
    real backtest run: trades where |Structure/Breakout| was unusually
    large were much more likely to reverse before reaching full TP
    (mean -4.9 to -5.9 for breakeven/partial-lock exits vs -2.8 to -2.9
    for full wins/losses) — consistent with an extreme reading marking
    an already-extended/climactic move rather than the start of one. If
    set, any signal whose |Structure/Breakout| score exceeds this value
    is skipped entirely, as if analyze_market had returned None."""
    all_frames = {}
    for symbol in symbols:
        try:
            all_frames[symbol] = load_symbol_frames(symbol, data_dir)
        except FileNotFoundError as e:
            print(f"  \u274c {e}")
    symbols = [s for s in symbols if s in all_frames]
    if not symbols:
        return [], {}

    all_close_times = sorted(set().union(
        *(set(all_frames[s]["1h"]["close_time"]) for s in symbols)
    ))
    if len(all_close_times) <= WARMUP_CANDLES:
        print(f"  \u26a0\ufe0f only {len(all_close_times)} total 1H timestamps available across "
              f"all symbols, need > {WARMUP_CANDLES} \u2014 nothing to simulate.")
        return [], {}

    state = fresh_portfolio_state()
    closed_trades = []
    per_symbol_closed = {s: [] for s in symbols}
    row_by_time = {
        s: all_frames[s]["1h"].set_index("close_time", drop=False) for s in symbols
    }

    for as_of_ms in all_close_times[WARMUP_CANDLES:]:
        as_of_dt = pd.to_datetime(as_of_ms, unit="ms", utc=True).to_pydatetime()

        if state.get("circuit_breaker"):
            cb_time = datetime.fromisoformat(state["circuit_breaker"])
            if as_of_dt < cb_time:
                continue
            state["circuit_breaker"] = None

        symbols_with_data_this_tick = []
        for symbol in symbols:
            if as_of_ms not in row_by_time[symbol].index:
                continue
            symbols_with_data_this_tick.append(symbol)
            row = row_by_time[symbol].loc[as_of_ms]
            current_high, current_low, current_close = row["high"], row["low"], row["close"]

            check_trailing_stop(state, current_high, current_low, symbol)
            just_closed = check_open_trades(state, current_high, current_low, current_close, symbol, as_of=as_of_dt)
            if just_closed:
                update_circuit_breaker(state, just_closed, as_of=as_of_dt)
                closed_trades.extend(just_closed)
                for t in just_closed:
                    per_symbol_closed[symbol].append(t)

        if state.get("circuit_breaker"):
            continue

        for symbol in symbols_with_data_this_tick:
            just_closed_this_symbol_this_tick = any(
                t["symbol"] == symbol for t in closed_trades
                if t.get("exit_time") == as_of_dt.isoformat()
            )
            if just_closed_this_symbol_this_tick:
                continue

            if is_symbol_on_cooldown(state, symbol, as_of=as_of_dt):
                continue
            if any(t.get("status") == "open" and t["symbol"] == symbol for t in state["trades"]):
                continue

            if has_reached_max_concurrent_trades(state):
                if verbose:
                    print(f"    [{as_of_dt.date()}] {symbol}: \u0633\u0642\u0641 \u0645\u0639\u0627\u0645\u0644\u0627\u062a \u0647\u0645\u200c\u0632\u0645\u0627\u0646 \u067e\u0631 \u0627\u0633\u062a")
                continue

            df_15m = slice_as_of(all_frames[symbol]["15m"], as_of_ms)
            df_1h = slice_as_of(all_frames[symbol]["1h"], as_of_ms)
            df_4h = slice_as_of(all_frames[symbol]["4h"], as_of_ms)
            df_1d = slice_as_of(all_frames[symbol]["1d"], as_of_ms)
            if len(df_1h) < 50 or len(df_4h) < 50:
                continue

            result = analyze_market(df_15m, df_1h, df_4h, df_1d, symbol, funding_rate=None)
            if not result:
                continue

            if max_abs_structure_score is not None:
                structure_score = (result.get("score_breakdown") or {}).get("Structure/Breakout", 0)
                if abs(structure_score) > max_abs_structure_score:
                    if verbose:
                        print(f"    [{as_of_dt.date()}] {symbol}: \u0631\u062f \u0634\u062f \u0628\u0647\u200c\u062e\u0627\u0637\u0631 \u0627\u0641\u0631\u0627\u0637 Structure/Breakout "
                              f"({structure_score:+d}, \u0622\u0633\u062a\u0627\u0646\u0647: {max_abs_structure_score})")
                    continue

            direction = result["direction"]
            atr = result["atr"]
            price = float(row_by_time[symbol].loc[as_of_ms]["close"])
            sl = price - (atr * config.ATR_SL_MULTIPLIER) if direction == "BUY" else price + (atr * config.ATR_SL_MULTIPLIER)
            tp = price + (atr * config.ATR_TP_MULTIPLIER) if direction == "BUY" else price - (atr * config.ATR_TP_MULTIPLIER)

            allowed, reason = can_open_trade(
                state, price, sl, tp, direction,
                max_daily_loss_r=config.MAX_DAILY_LOSS_R,
                max_open_risk_r=config.MAX_OPEN_RISK_R,
                min_reward_risk=config.MIN_REWARD_RISK,
                daily_loss_r=todays_realized_loss_r(closed_trades, as_of_dt),
                max_same_direction_open=config.MAX_SAME_DIRECTION_OPEN,
            )
            if not allowed:
                if verbose:
                    print(f"    [{as_of_dt.date()}] {symbol}: \u0633\u06cc\u06af\u0646\u0627\u0644 \u0631\u062f \u0634\u062f \u2014 {reason}")
                continue

            state["trades"].append({
                "symbol": symbol, "direction": direction, "entry": price, "tp": tp, "sl": sl,
                "initial_risk": abs(price - sl), "status": "open",
                "sl_moved_to_breakeven": False, "sl_partial_lock_done": False,
                "time": as_of_dt.isoformat(),
                "score_breakdown": result.get("score_breakdown"),
            })
            if verbose:
                print(f"    [{as_of_dt.date()}] {symbol}: {direction} @ {price:.4f} (SL {sl:.4f}, TP {tp:.4f})")

    still_open = [t for t in state["trades"] if t.get("status") == "open"]
    if still_open:
        print(f"  \u2139\ufe0f {len(still_open)} \u0645\u0639\u0627\u0645\u0644\u0647 \u062f\u0631 \u0645\u062d\u06cc\u0637 \u0628\u0627\u0632.")

    return closed_trades, per_symbol_closed


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--symbols", required=True, help="Comma-separated, e.g. BTCUSDT,ETHUSDT")
    parser.add_argument("--data-dir", default="backtest_data")
    parser.add_argument("--fee-r", type=float, default=0.02)
    parser.add_argument("--slippage-r", type=float, default=0.02)
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument(
        "--max-abs-structure-score", type=float, default=None,
        help="EXPERIMENTAL: reject any signal whose |Structure/Breakout| "
             "score exceeds this value. Tests the hypothesis that an "
             "unusually strong structure/breakout reading marks an "
             "already-extended move rather than the start of one. "
             "Leave unset to disable (default live behavior).",
    )
    args = parser.parse_args()

    symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]
    print(f"\n=== \u0628\u06a9\u200c\u062a\u0633\u062a \u067e\u0631\u062a\u0641\u0648\u06cc \u0645\u0634\u062a\u0631\u06a9: {', '.join(symbols)} ===")
    if args.max_abs_structure_score is not None:
        print(f"(\u0622\u0632\u0645\u0627\u06cc\u0634\u06cc: \u0631\u062f \u0633\u06cc\u06af\u0646\u0627\u0644 \u0627\u06af\u0631 |Structure/Breakout| > {args.max_abs_structure_score})")
    all_closed, per_symbol = run_portfolio_backtest(
        symbols, args.data_dir, verbose=args.verbose,
        max_abs_structure_score=args.max_abs_structure_score,
    )

    if not all_closed:
        print("\n\u0647\u06cc\u0686 \u0645\u0639\u0627\u0645\u0644\u0647\u200c\u0627\u06cc \u062f\u0631 \u06a9\u0644 \u0628\u0627\u0632\u0647\u0654 \u062f\u0627\u062f\u0647 \u0634\u0628\u06cc\u0647\u200c\u0633\u0627\u0632\u06cc \u0646\u0634\u062f.")
        return

    r_multiples = [t["r_multiple"] for t in all_closed]
    metrics = summarize_r_multiples(r_multiples, fee_r_per_trade=args.fee_r, slippage_r_per_trade=args.slippage_r)

    print(f"\n{'=' * 55}")
    print("\u0646\u062a\u06cc\u062c\u0647\u0654 \u06a9\u0644\u06cc \u0628\u06a9\u200c\u062a\u0633\u062a \u067e\u0631\u062a\u0641\u0648\u06cc")
    print(f"{'=' * 55}")
    print(f"\u062a\u0639\u062f\u0627\u062f \u0645\u0639\u0627\u0645\u0644\u0627\u062a: {metrics.trades}")
    print(f"\u0628\u0631\u062f: {metrics.wins} | \u0628\u0627\u062e\u062a: {metrics.losses} | \u0646\u0631\u062e \u0628\u0631\u062f: {metrics.win_rate:.1f}%")
    print(f"\u0645\u062c\u0645\u0648\u0639 R \u062e\u0627\u0644\u0635: {metrics.net_r:+.2f}")
    print(f"Expectancy: {metrics.expectancy_r:+.3f}")
    print(f"Profit Factor: {metrics.profit_factor:.2f}")
    print(f"Max Drawdown: {metrics.max_drawdown_r:.2f}R")

    print("\n--- \u062a\u0641\u06a9\u06cc\u06a9 \u0628\u0647\u200c\u0627\u0632\u0627\u06cc \u0647\u0631 \u0646\u0645\u0627\u062f ---")
    for symbol in symbols:
        closed = per_symbol.get(symbol, [])
        if not closed:
            print(f"{symbol}: \u0647\u06cc\u0686 \u0645\u0639\u0627\u0645\u0644\u0647\u200c\u0627\u06cc")
            continue
        sym_metrics = summarize_r_multiples(
            [t["r_multiple"] for t in closed], fee_r_per_trade=args.fee_r, slippage_r_per_trade=args.slippage_r
        )
        print(f"{symbol}: {sym_metrics.trades} \u0645\u0639\u0627\u0645\u0644\u0647 | \u0646\u0631\u062e \u0628\u0631\u062f {sym_metrics.win_rate:.1f}% | "
              f"R \u062e\u0627\u0644\u0635 {sym_metrics.net_r:+.2f} | Expectancy {sym_metrics.expectancy_r:+.3f}")

    os.makedirs(args.data_dir, exist_ok=True)
    out_path = os.path.join(args.data_dir, "backtest_results.csv")
    export_rows = []
    for t in all_closed:
        row = dict(t)
        breakdown = row.pop("score_breakdown", None) or {}
        row["score_breakdown"] = "; ".join(f"{k}={v:+.0f}" for k, v in breakdown.items())
        export_rows.append(row)
    pd.DataFrame(export_rows).to_csv(out_path, index=False)
    print(f"\n\u062c\u0632\u0626\u06cc\u0627\u062a \u06a9\u0627\u0645\u0644: {out_path}")


if __name__ == "__main__":
    main()
