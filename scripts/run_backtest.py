"""Portfolio backtest over historical data, reusing the live bot's actual
decision logic (indicators.analyze_market, trade_monitor's trailing-stop /
close checks, risk_engine.can_open_trade) rather than a separate
reimplementation -- so backtest results reflect what the live bot would
really have done, not an approximation of it.

Requires historical CSVs already fetched via
scripts/fetch_historical_klines.py into --data-dir (one file per
"{symbol}_{interval}.csv", columns: open_time, open, high, low, close,
volume, taker_buy_volume).

Walks forward tick-by-tick over the union of every symbol's 1H candle
timestamps. At each tick, for each symbol with a candle at that time (in a
fixed, deterministic order), it:
  1. builds "as-of-now" slices of that symbol's 15m/1h/4h/1d data --
     everything with open_time <= the current 1h candle's open_time, and
     nothing after it, so the strategy never sees the future
  2. runs the exact same trailing-stop / TP-SL close checks the live bot
     runs each cycle (trade_monitor.check_trailing_stop,
     trade_monitor.check_open_trades)
  3. if no trade is open on that symbol this tick, calls
     indicators.analyze_market(...) and, on a signal, computes SL/TP with
     the same ATR multipliers main.py uses and gates the open through
     risk_engine.can_open_trade -- the same portfolio-wide risk checks
     (MAX_CONCURRENT_TRADES, MAX_OPEN_RISK_R, MAX_DAILY_LOSS_R,
     MAX_SAME_DIRECTION_OPEN) apply here too, since all symbols share one
     state["trades"] list just like live trading does

SMART_CONTEXT_MODE=backtest and NEWS_ENABLED=0 are forced at the top so
news_provider.fundamental_score() never makes a live network call scored
against a historical candle (that would be look-ahead bias). WHALE_BIAS_FILE
is deliberately left unset here for the same reason -- see the whale_bias
section of README_V28_SMART_CONTEXT.md.

Usage:
    python scripts/run_backtest.py --symbols BTCUSDT,ETHUSDT --data-dir backtest_data
    python scripts/run_backtest.py --data-dir backtest_data   # all configured symbols
"""
import argparse
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

os.environ.setdefault("SMART_CONTEXT_MODE", "backtest")
os.environ.setdefault("NEWS_ENABLED", "0")
os.environ.pop("WHALE_BIAS_FILE", None)
os.environ.pop("WHALE_BIAS_JSON", None)

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd  # noqa: E402

from config import (  # noqa: E402
    SYMBOLS, ATR_SL_MULTIPLIER, ATR_TP_MULTIPLIER,
    MAX_DAILY_LOSS_R, MAX_OPEN_RISK_R, MIN_REWARD_RISK, MAX_SAME_DIRECTION_OPEN,
    MAX_CONCURRENT_TRADES,
)
from indicators import analyze_market, MIN_CANDLES  # noqa: E402
from trade_monitor import check_open_trades, check_trailing_stop  # noqa: E402
from risk_engine import can_open_trade  # noqa: E402

INTERVALS = ["15m", "1h", "4h", "1d"]
MIN_1H_HISTORY = MIN_CANDLES  # matches analyze_market's own len(df_1h) requirement -- no point calling it before this


def load_symbol_data(data_dir, symbol):
    frames = {}
    for interval in INTERVALS:
        path = Path(data_dir) / f"{symbol}_{interval}.csv"
        if not path.exists():
            return None
        df = pd.read_csv(path)
        if df.empty:
            return None
        frames[interval] = df.sort_values("open_time").reset_index(drop=True)
    return frames


def has_reached_max_concurrent(state):
    if MAX_CONCURRENT_TRADES <= 0:
        return False
    return sum(1 for t in state["trades"] if t.get("status") == "open") >= MAX_CONCURRENT_TRADES


def already_open(state, symbol):
    return any(t.get("status") == "open" and t["symbol"] == symbol for t in state["trades"])


def daily_loss_r_asof(closed_history, now_dt):
    today = now_dt.date().isoformat()
    total = 0.0
    for t in closed_history:
        if t.get("result") == "LOSS" and str(t.get("exit_time", "")).startswith(today):
            total += abs(t.get("r_multiple", 0.0))
    return total


def run_backtest(symbols, data_dir):
    per_symbol_data = {}
    for symbol in symbols:
        data = load_symbol_data(data_dir, symbol)
        if data is None:
            print(f"  skip {symbol}: missing/empty historical CSVs in {data_dir}")
            continue
        per_symbol_data[symbol] = data

    if not per_symbol_data:
        print("No symbols had usable historical data -- nothing to backtest.")
        return [], []

    # Union of every symbol's 1H timestamps, walked in order.
    all_ticks = sorted(set().union(*[
        set(data["1h"]["open_time"].tolist()) for data in per_symbol_data.values()
    ]))

    state = {"trades": [], "stats": {"wins": 0, "losses": 0, "streak": 0}, "symbol_cooldowns": {}}
    closed_history = []

    for tick_i, tick_time in enumerate(all_ticks):
        for symbol in sorted(per_symbol_data.keys()):
            data = per_symbol_data[symbol]
            df_1h_full = data["1h"]
            idx_matches = df_1h_full.index[df_1h_full["open_time"] == tick_time]
            if len(idx_matches) == 0:
                continue
            idx = idx_matches[0]
            if idx < MIN_1H_HISTORY:
                continue

            df_1h = df_1h_full.iloc[: idx + 1]
            current_high = float(df_1h["high"].iloc[-1])
            current_low = float(df_1h["low"].iloc[-1])
            current_close = float(df_1h["close"].iloc[-1])

            check_trailing_stop(state, current_high, current_low, symbol)
            closed = check_open_trades(state, current_high, current_low, current_close, symbol)
            for trade in closed:
                # check_open_trades() stamps exit_time with the real wall-
                # clock "now" (it's shared production code) -- overwrite it
                # with the simulated historical tick time so date-bucketed
                # checks (daily_loss_r_asof below) use the right day.
                trade["exit_time"] = datetime.fromtimestamp(tick_time / 1000, tz=timezone.utc).isoformat()
                trade["exit_time_ms"] = int(tick_time)
                closed_history.append(trade)
                if trade["result"] == "WIN":
                    state["stats"]["wins"] += 1
                    state["stats"]["streak"] = 0
                else:
                    state["stats"]["losses"] += 1
                    state["stats"]["streak"] += 1
            if closed:
                continue  # matches live behavior: wait a tick before re-entering

            if already_open(state, symbol) or has_reached_max_concurrent(state):
                continue

            df_4h = data["4h"][data["4h"]["open_time"] <= tick_time]
            df_1d = data["1d"][data["1d"]["open_time"] <= tick_time]
            df_15m = data["15m"][data["15m"]["open_time"] <= tick_time]
            if df_4h.empty or df_1d.empty:
                continue

            result = analyze_market(df_15m, df_1h, df_4h, df_1d, symbol, funding_rate=None, reasons=[])
            if not result:
                continue

            direction = result["direction"]
            price = result["price"]
            atr = result["atr"]
            sl = price - (atr * ATR_SL_MULTIPLIER) if direction == "BUY" else price + (atr * ATR_SL_MULTIPLIER)
            tp = price + (atr * ATR_TP_MULTIPLIER) if direction == "BUY" else price - (atr * ATR_TP_MULTIPLIER)

            now_dt = datetime.fromtimestamp(tick_time / 1000, tz=timezone.utc)
            allowed, _reason = can_open_trade(
                state, price, sl, tp, direction,
                max_daily_loss_r=MAX_DAILY_LOSS_R,
                max_open_risk_r=MAX_OPEN_RISK_R,
                min_reward_risk=MIN_REWARD_RISK,
                daily_loss_r=daily_loss_r_asof(closed_history, now_dt),
                max_same_direction_open=MAX_SAME_DIRECTION_OPEN,
            )
            if not allowed:
                continue

            state["trades"].append({
                "symbol": symbol, "direction": direction, "entry": price,
                "tp": tp, "sl": sl, "initial_risk": abs(price - sl),
                "status": "open", "sl_warning_sent": False,
                "sl_moved_to_breakeven": False, "sl_partial_lock_done": False,
                "time": now_dt.isoformat(), "entry_time_ms": int(tick_time),
            })

        if (tick_i + 1) % 500 == 0:
            print(f"  ...{tick_i + 1}/{len(all_ticks)} ticks, "
                  f"{len(closed_history)} closed, "
                  f"{sum(1 for t in state['trades'] if t['status'] == 'open')} open")

    still_open = [t for t in state["trades"] if t.get("status") == "open"]
    return closed_history, still_open


def summarize(closed_history, still_open, symbols):
    lines = []
    lines.append(f"Backtest results -- {len(symbols)} symbol(s), {datetime.now(timezone.utc).isoformat()}")
    lines.append("=" * 70)
    if not closed_history:
        lines.append("No trades closed in this window.")
    else:
        wins = [t for t in closed_history if t["result"] == "WIN"]
        losses = [t for t in closed_history if t["result"] == "LOSS"]
        total_r = sum(t.get("r_multiple", 0.0) for t in closed_history)
        lines.append(f"Total closed trades : {len(closed_history)}")
        lines.append(f"Wins / Losses       : {len(wins)} / {len(losses)}")
        lines.append(f"Win rate            : {len(wins) / len(closed_history) * 100:.1f}%")
        lines.append(f"Total R             : {total_r:+.2f}R")
        lines.append(f"Avg R / trade       : {total_r / len(closed_history):+.3f}R")
        lines.append(f"Still open at end   : {len(still_open)}")
        lines.append("")
        lines.append("Per-symbol breakdown:")
        for symbol in sorted(symbols):
            sym_trades = [t for t in closed_history if t["symbol"] == symbol]
            if not sym_trades:
                lines.append(f"  {symbol}: 0 closed trades")
                continue
            sym_wins = sum(1 for t in sym_trades if t["result"] == "WIN")
            sym_r = sum(t.get("r_multiple", 0.0) for t in sym_trades)
            lines.append(
                f"  {symbol}: {len(sym_trades)} trades, "
                f"{sym_wins}/{len(sym_trades)} won "
                f"({sym_wins / len(sym_trades) * 100:.0f}%), {sym_r:+.2f}R total"
            )
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbols", type=str, default="", help="Comma-separated symbols (default: all of config.SYMBOLS with data present)")
    parser.add_argument("--data-dir", type=str, default="backtest_data")
    parser.add_argument("--out", type=str, default="backtest_results.csv")
    args = parser.parse_args()

    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()] or SYMBOLS
    data_dir = Path(args.data_dir)
    if not data_dir.exists():
        print(f"'{data_dir}' does not exist. Run scripts/fetch_historical_klines.py first.")
        return 0

    print(f"Running backtest for {len(symbols)} candidate symbol(s) from {data_dir}...")
    closed_history, still_open = run_backtest(symbols, data_dir)

    used_symbols = sorted(set(t["symbol"] for t in closed_history) | set(t["symbol"] for t in still_open))
    summary = summarize(closed_history, still_open, used_symbols or symbols)
    print(summary)

    if closed_history:
        pd.DataFrame(closed_history).to_csv(args.out, index=False)
        print(f"\nWrote {len(closed_history)} closed trades -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
