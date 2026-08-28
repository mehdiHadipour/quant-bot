"""Download historical OHLCV klines for backtesting.

Routes each symbol to the same data source main.py's live cycle would use
for it (WEEX for config.WEEX_SYMBOLS, Binance for everything else), so a
backtest run reflects the same tradable universe as the live bot.

Paginates backward from "now" in --limit-sized chunks until --days is
covered, and writes one CSV per symbol/interval to --out-dir, matching the
same columns data_engine.fetch_klines() returns (so run_backtest.py can
build the exact same shape of DataFrame analyze_market() expects live).

Usage:
    python scripts/fetch_historical_klines.py --symbols BTCUSDT,ETHUSDT,XAUUSDT --days 180
    python scripts/fetch_historical_klines.py --all --days 90
"""
import argparse
import math
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import SYMBOLS, WEEX_SYMBOLS  # noqa: E402
from indicators import MIN_CANDLES  # noqa: E402

BINANCE_BASE_URLS = [
    "https://data-api.binance.vision/api/v3/klines",
    "https://api.binance.com/api/v3/klines",
]
WEEX_BASE_URL = "https://api-spot.weex.com/api/v3/market/klines"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; AIQuantBot-Backtest/1.0)"}
INTERVALS = ["15m", "1h", "4h", "1d"]
INTERVAL_MS = {
    "15m": 15 * 60 * 1000,
    "1h": 3600 * 1000,
    "4h": 4 * 3600 * 1000,
    "1d": 24 * 3600 * 1000,
}
# analyze_market() requires at least MIN_CANDLES (indicators.py, currently
# 210) of history on the 1H, 4H, AND 1D timeframes before it will produce
# ANY signal -- get_timeframe_bias(df_1d) silently returns None (and the
# 1D-confirmation gate then always rejects) until df_1d itself has 210
# candles, i.e. 210 *days*. A `--days 90` (or even the old `--days 180`)
# fetch only ever gave the 1D CSV 90 (or 180) rows -- always short of 210
# -- so EVERY signal that reached the 1D gate was silently and permanently
# rejected for the entire simulation window, regardless of market
# conditions. Live trading doesn't hit this: main.py always fetches up to
# 300 candles per timeframe (data_engine.fetch_klines's default limit),
# comfortably above 210 on every timeframe including 1D. To match that
# here, each interval's fetch window is the requested --days *plus* enough
# extra lead-in days to cover MIN_CANDLES candles of warm-up on that
# timeframe -- so by the first day of the actual --days simulation window,
# every timeframe already has full indicator history.
_WARMUP_DAYS = {
    interval: math.ceil(MIN_CANDLES * ms / (24 * 3600 * 1000))
    for interval, ms in INTERVAL_MS.items()
}
_WEEX_SET = set(WEEX_SYMBOLS)
# Flat safety margin added on top of each interval's own warmup: the 1H
# walk-forward loop's own earliest tick is itself a few days before
# "now - days" (its own ~9-day warmup), and the 4H/1D warmup requirement
# applies relative to THAT earliest tick, not to "now" -- so without this,
# the very first few days of the requested window could still fall a
# little short on 1D history. A flat buffer is simpler and safer than
# compounding each interval's warmup into every other interval's.
_SAFETY_MARGIN_DAYS = 15


def _rows_to_df(rows):
    return pd.DataFrame([{
        "open_time": int(r[0]),
        "open": float(r[1]),
        "high": float(r[2]),
        "low": float(r[3]),
        "close": float(r[4]),
        "volume": float(r[5]),
        "taker_buy_volume": float(r[9]),
    } for r in rows])


def _fetch_page_binance(symbol, interval, end_time_ms, limit=1000):
    params = {"symbol": symbol, "interval": interval, "limit": limit, "endTime": end_time_ms}
    for base_url in BINANCE_BASE_URLS:
        try:
            resp = requests.get(base_url, params=params, headers=HEADERS, timeout=20)
            if resp.status_code == 200:
                return resp.json()
            time.sleep(0.5)
        except requests.RequestException:
            time.sleep(0.5)
    return None


def _fetch_page_weex(symbol, interval, end_time_ms, limit=1000):
    params = {"symbol": symbol, "interval": interval, "limit": limit, "endTime": end_time_ms}
    try:
        resp = requests.get(WEEX_BASE_URL, params=params, headers=HEADERS, timeout=20)
        if resp.status_code == 200:
            return resp.json()
    except requests.RequestException:
        pass
    return None


def fetch_historical(symbol, interval, days, limit=1000):
    """Paginate backward from now until `days` of history is covered.
    Returns a DataFrame sorted ascending by open_time, deduplicated.
    """
    fetch_page = _fetch_page_weex if symbol in _WEEX_SET else _fetch_page_binance
    target_start_ms = int(time.time() * 1000) - days * 24 * 3600 * 1000
    end_time_ms = int(time.time() * 1000)

    all_rows = []
    seen_oldest = None
    attempts_without_progress = 0
    while end_time_ms > target_start_ms and attempts_without_progress < 6:
        rows = fetch_page(symbol, interval, end_time_ms, limit)
        if not rows:
            attempts_without_progress += 1
            time.sleep(min(1.0 * attempts_without_progress, 5.0))  # backoff under load
            continue
        all_rows.extend(rows)
        oldest_open_time = int(rows[0][0])
        if seen_oldest is not None and oldest_open_time >= seen_oldest:
            break  # not making progress backward; avoid an infinite loop
        seen_oldest = oldest_open_time
        end_time_ms = oldest_open_time - 1
        attempts_without_progress = 0
        time.sleep(0.15)  # be polite to the public API

    if not all_rows:
        return None

    df = _rows_to_df(all_rows)
    df = df.drop_duplicates(subset="open_time").sort_values("open_time").reset_index(drop=True)
    df = df[df["open_time"] >= target_start_ms].reset_index(drop=True)
    return df


def _fetch_and_save(symbol, interval, days, out_dir):
    source = "WEEX" if symbol in _WEEX_SET else "Binance"
    total_days = days + _WARMUP_DAYS[interval] + _SAFETY_MARGIN_DAYS
    df = fetch_historical(symbol, interval, total_days)
    out_path = out_dir / f"{symbol}_{interval}.csv"
    if df is None or df.empty:
        return symbol, interval, source, 0, out_path
    df.to_csv(out_path, index=False)
    return symbol, interval, source, len(df), out_path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbols", type=str, default="", help="Comma-separated symbols (default: all of config.SYMBOLS)")
    parser.add_argument("--all", action="store_true", help="Fetch every symbol in config.SYMBOLS")
    parser.add_argument("--days", type=int, default=180, help="Days of history to fetch")
    parser.add_argument("--out-dir", type=str, default="backtest_data", help="Output directory for CSVs")
    parser.add_argument("--workers", type=int, default=12, help="Concurrent (symbol, interval) fetch jobs")
    args = parser.parse_args()

    if args.symbols.strip():
        symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    elif args.all:
        symbols = SYMBOLS
    else:
        symbols = SYMBOLS
        print(f"No --symbols given; defaulting to all {len(symbols)} configured symbols.")

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    jobs = [(symbol, interval) for symbol in symbols for interval in INTERVALS]
    print(f"Fetching {len(jobs)} (symbol, interval) combinations "
          f"across {len(symbols)} symbol(s) with {args.workers} parallel workers...")
    print(f"Requested simulation window: {args.days}d. Actual fetch per interval "
          f"(includes indicator warm-up so the full {args.days}d window is tradable "
          f"from day 1): "
          + ", ".join(f"{i}={args.days + _WARMUP_DAYS[i] + _SAFETY_MARGIN_DAYS}d" for i in INTERVALS))

    done = 0
    warnings = 0
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {
            executor.submit(_fetch_and_save, symbol, interval, args.days, out_dir): (symbol, interval)
            for symbol, interval in jobs
        }
        for future in as_completed(futures):
            symbol, interval = futures[future]
            try:
                sym, ivl, source, n_rows, out_path = future.result()
            except Exception as e:  # noqa: BLE001 - one bad symbol must not kill the whole run
                print(f"  ERROR {symbol} {interval}: {e}")
                warnings += 1
                continue
            done += 1
            if n_rows == 0:
                print(f"  [{done}/{len(jobs)}] WARNING: no data for {sym} {ivl} ({source}) -- skipping")
                warnings += 1
            else:
                print(f"  [{done}/{len(jobs)}] {sym} {ivl} ({source}): {n_rows} candles -> {out_path}")

    print(f"Done. {done - warnings} succeeded, {warnings} warning(s)/error(s), out of {len(jobs)} total.")


if __name__ == "__main__":
    main()
