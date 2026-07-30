"""
Walk-forward backtest: replays historical data through the SAME
production functions the live bot uses every cycle —
indicators.analyze_market, trade_monitor.{is_symbol_on_cooldown,
check_trailing_stop, check_open_trades, update_circuit_breaker}, and
risk_engine.can_open_trade — so backtest behavior can't silently drift
from live behavior. Only the data source (local historical CSVs instead
of live API calls) and the absence of Telegram/git side effects differ.

REQUIRES: run scripts/fetch_historical_klines.py first.

USAGE:
    python scripts/run_backtest.py --symbols BTCUSDT,ETHUSDT

KNOWN SIMPLIFICATIONS (v1 — read before trusting the numbers):
  - Backtests are still run symbol-by-symbol, so the daily-loss guard is
    per-symbol rather than a true cross-symbol portfolio ledger.
  - Funding rate is not replayed (no historical funding data fetched),
    so funding_score is always 0 here, same as when it's simply
    unavailable live — never blocks a signal either way.
  - Symbols are backtested one at a time, independently. MAX_CONCURRENT_TRADES
    and MAX_SAME_DIRECTION_OPEN are enforced only WITHIN a symbol's own
    run (trivially: at most 1 trade open per symbol at a time, since a
    symbol never stacks a second trade on itself), not across symbols
    running in the same historical window — a true portfolio-level
    backtest across all symbols simultaneously is a bigger v2 change.
  - Cooldown/circuit-breaker timing is evaluated once per 1H candle (the
    bot's primary decision timeframe), not on the live bot's actual
    10-minute wake-up cadence — verified by testing that a cooldown can
    expire up to one full 1H-candle-boundary sooner or later here than
    it would live. This is an intentional simplification (there's no
    extra information to gain from checking more often than the data
    itself changes), but means cooldown re-entry timing is approximate,
    not exact, versus live behavior.
  - This was built and logic-tested (pagination, no-lookahead slicing,
    historical-time replay for cooldowns, full open->trail->close->
    cooldown lifecycle) in a sandboxed review environment with NO
    network access to real market data — the mechanics are verified
    against synthetic data, but the actual downloaded data and resulting
    numbers have not been eyeballed against a real run. Sanity check the
    first run's trade count and date range before trusting it.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd

from indicators import analyze_market
from trade_monitor import (
    is_symbol_on_cooldown, check_trailing_stop, check_open_trades, update_circuit_breaker,
)
from risk_engine import can_open_trade
from research import summarize_r_multiples
import config

WARMUP_CANDLES = 250  # enough history for every indicator (ADX, EMA200, etc.) to be valid
ROLLING_WINDOW = 300  # matches the live bot's typical fetch size


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
    live bot uses so indicator behavior matches (a much longer history
    changes e.g. EMA200's early values)."""
    sliced = df[df["close_time"] <= as_of_close_time]
    return sliced.tail(ROLLING_WINDOW).reset_index(drop=True)


def fresh_state():
    return {
        "trades": [],
        "stats": {"wins": 0, "losses": 0, "streak": 0, "equity_r": 0.0,
                   "peak_equity_r": 0.0, "max_drawdown_r": 0.0,
                   "gross_profit_r": 0.0, "gross_loss_r": 0.0},
        "circuit_breaker": None,
        "symbol_cooldowns": {},
    }


def _daily_loss_r(closed_trades, day):
    """Realized negative R for one UTC trading day, used by the backtest
    exactly as the live risk guard is intended to behave."""
    total = 0.0
    for trade in closed_trades:
        if trade.get("result") != "LOSS":
            continue
        exit_time = trade.get("exit_time")
        if not exit_time:
            continue
        try:
            if pd.to_datetime(exit_time, utc=True).date() == day:
                total += abs(float(trade.get("r_multiple", 0.0)))
        except (TypeError, ValueError):
            continue
    return total


def run_symbol_backtest(symbol, data_dir, verbose=False):
    frames = load_symbol_frames(symbol, data_dir)
    df_1h_all = frames["1h"]
    state = fresh_state()
    closed_trades = []

    if len(df_1h_all) <= WARMUP_CANDLES:
        print(f"  ⚠️ only {len(df_1h_all)} 1H candles available, need > {WARMUP_CANDLES} — skipping {symbol}")
        return []

    for i in range(WARMUP_CANDLES, len(df_1h_all)):
        row = df_1h_all.iloc[i]
        as_of_ms = int(row["close_time"])
        as_of_dt = pd.to_datetime(as_of_ms, unit="ms", utc=True).to_pydatetime()
        current_high, current_low, current_close = row["high"], row["low"], row["close"]

        # Circuit breaker: mirror main.py's check (simplified — no
        # partial-cooldown-window re-check on resume, matches live intent).
        if state.get("circuit_breaker"):
            from datetime import datetime as _dt
            cb_time = _dt.fromisoformat(state["circuit_breaker"])
            if as_of_dt < cb_time:
                continue
            state["circuit_breaker"] = None

        # 1) Manage any existing open trade first (mirrors process_symbol's order).
        check_trailing_stop(state, current_high, current_low, symbol)
        just_closed = check_open_trades(state, current_high, current_low, current_close, symbol, as_of=as_of_dt)
        if just_closed:
            update_circuit_breaker(state, just_closed, as_of=as_of_dt)
            closed_trades.extend(just_closed)
            continue  # same as live: skip new-signal analysis the cycle a trade closes

        if is_symbol_on_cooldown(state, symbol, as_of=as_of_dt):
            continue
        if any(t.get("status") == "open" for t in state["trades"]):
            continue  # this symbol already has an open trade

        # 2) New-signal analysis — CLOSED candles only, exactly like the
        # live v27.5 fix (the "as of this point in time" slice for every
        # timeframe IS already only closed data, since real historical
        # candles are all closed by definition).
        df_15m = slice_as_of(frames["15m"], as_of_ms)
        df_1h = slice_as_of(df_1h_all, as_of_ms)
        df_4h = slice_as_of(frames["4h"], as_of_ms)
        df_1d = slice_as_of(frames["1d"], as_of_ms)
        if len(df_1h) < 50 or len(df_4h) < 50:
            continue

        result = analyze_market(df_15m, df_1h, df_4h, df_1d, symbol, funding_rate=None)
        if not result:
            continue

        direction = result["direction"]
        atr = result["atr"]
        price = float(current_close)
        sl = price - (atr * config.ATR_SL_MULTIPLIER) if direction == "BUY" else price + (atr * config.ATR_SL_MULTIPLIER)
        tp = price + (atr * config.ATR_TP_MULTIPLIER) if direction == "BUY" else price - (atr * config.ATR_TP_MULTIPLIER)

        allowed, reason = can_open_trade(
            state, price, sl, tp, direction,
            max_daily_loss_r=config.MAX_DAILY_LOSS_R,
            max_open_risk_r=config.MAX_OPEN_RISK_R,
            min_reward_risk=config.MIN_REWARD_RISK,
            daily_loss_r=_daily_loss_r(closed_trades, as_of_dt.date()),
            max_same_direction_open=config.MAX_SAME_DIRECTION_OPEN,
        )
        if not allowed:
            if verbose:
                print(f"    [{as_of_dt.date()}] {symbol}: سیگنال رد شد — {reason}")
            continue

        state["trades"].append({
            "symbol": symbol, "direction": direction, "entry": price, "tp": tp, "sl": sl,
            "initial_risk": abs(price - sl), "status": "open",
            "sl_moved_to_breakeven": False, "sl_partial_lock_done": False,
            "time": as_of_dt.isoformat(),
        })
        if verbose:
            print(f"    [{as_of_dt.date()}] {symbol}: {direction} @ {price:.4f} (SL {sl:.4f}, TP {tp:.4f})")

    still_open = [t for t in state["trades"] if t.get("status") == "open"]
    if still_open:
        print(f"  ℹ️ {len(still_open)} معاملهٔ {symbol} در پایان دادهٔ تاریخی هنوز باز بود "
              f"(نه برد نه باخت — در آمار نهایی لحاظ نمی‌شود، چون بازارش تمام نشده بود).")

    return closed_trades


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--symbols", required=True, help="Comma-separated, e.g. BTCUSDT,ETHUSDT")
    parser.add_argument("--data-dir", default="backtest_data")
    parser.add_argument("--fee-r", type=float, default=0.02,
                         help="Estimated round-trip fee, in units of R, subtracted from every trade (default 0.02R)")
    parser.add_argument("--slippage-r", type=float, default=0.02,
                         help="Estimated round-trip slippage, in units of R (default 0.02R)")
    parser.add_argument("--verbose", action="store_true", help="Print every signal/rejection as it's simulated")
    args = parser.parse_args()

    symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]
    all_closed = []
    per_symbol = {}

    for symbol in symbols:
        print(f"\n=== در حال بک‌تست {symbol} ===")
        try:
            closed = run_symbol_backtest(symbol, args.data_dir, verbose=args.verbose)
        except FileNotFoundError as e:
            print(f"  ❌ {e}")
            continue
        per_symbol[symbol] = closed
        all_closed.extend(closed)
        print(f"  {len(closed)} معاملهٔ بسته‌شده برای {symbol}")

    if not all_closed:
        print("\nهیچ معامله‌ای در کل بازهٔ داده شبیه‌سازی نشد.")
        return

    r_multiples = [t["r_multiple"] for t in all_closed]
    metrics = summarize_r_multiples(r_multiples, fee_r_per_trade=args.fee_r, slippage_r_per_trade=args.slippage_r)

    print(f"\n{'=' * 55}")
    print("نتیجهٔ کلی بک‌تست (پس از کسر کارمزد/لغزش تخمینی)")
    print(f"{'=' * 55}")
    print(f"تعداد معاملات: {metrics.trades}")
    print(f"برد: {metrics.wins} | باخت: {metrics.losses} | نرخ برد: {metrics.win_rate:.1f}%")
    print(f"مجموع R خالص: {metrics.net_r:+.2f}")
    print(f"میانگین R هر معامله (Expectancy): {metrics.expectancy_r:+.3f}")
    print(f"Profit Factor: {metrics.profit_factor:.2f}")
    print(f"حداکثر افت سرمایه (Max Drawdown): {metrics.max_drawdown_r:.2f}R")

    print("\n--- تفکیک به‌ازای هر نماد ---")
    for symbol, closed in per_symbol.items():
        if not closed:
            print(f"{symbol}: هیچ معامله‌ای")
            continue
        sym_metrics = summarize_r_multiples(
            [t["r_multiple"] for t in closed], fee_r_per_trade=args.fee_r, slippage_r_per_trade=args.slippage_r
        )
        buys = [t for t in closed if t.get("direction") == "BUY"]
        sells = [t for t in closed if t.get("direction") == "SELL"]
        print(f"{symbol}: {sym_metrics.trades} معامله | نرخ برد {sym_metrics.win_rate:.1f}% | "
              f"R خالص {sym_metrics.net_r:+.2f} | Expectancy {sym_metrics.expectancy_r:+.3f} | "
              f"BUY={len(buys)} / SELL={len(sells)}")

    os.makedirs(args.data_dir, exist_ok=True)
    out_path = os.path.join(args.data_dir, "backtest_results.csv")
    pd.DataFrame(all_closed).to_csv(out_path, index=False)
    print(f"\nجزئیات کامل هر معامله: {out_path}")


if __name__ == "__main__":
    main()
