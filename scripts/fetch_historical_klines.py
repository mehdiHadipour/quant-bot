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
import sys
import time
from pathlib import Path

import requests
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import SYMBOLS, WEEX_SYMBOLS  # noqa: E402

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
_WEEX_SET = set(WEEX_SYMBOLS)


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
    while end_time_ms > target_start_ms and attempts_without_progress < 3:
        rows = fetch_page(symbol, interval, end_time_ms, limit)
        if not rows:
            attempts_without_progress += 1
            time.sleep(1)
            continue
        all_rows.extend(rows)
        oldest_open_time = int(rows[0][0])
        if seen_oldest is not None and oldest_open_time >= seen_oldest:
            break  # not making progress backward; avoid an infinite loop
        seen_oldest = oldest_open_time
        end_time_ms = oldest_open_time - 1
        attempts_without_progress = 0
        time.sleep(0.25)  # be polite to the public API

    if not all_rows:
        return None

    df = _rows_to_df(all_rows)
    df = df.drop_duplicates(subset="open_time").sort_values("open_time").reset_index(drop=True)
    df = df[df["open_time"] >= target_start_ms].reset_index(drop=True)
    return df


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbols", type=str, default="", help="Comma-separated symbols (default: all of config.SYMBOLS)")
    parser.add_argument("--all", action="store_true", help="Fetch every symbol in config.SYMBOLS")
    parser.add_argument("--days", type=int, default=180, help="Days of history to fetch")
    parser.add_argument("--out-dir", type=str, default="backtest_data", help="Output directory for CSVs")
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

    for symbol in symbols:
        source = "WEEX" if symbol in _WEEX_SET else "Binance"
        for interval in INTERVALS:
            print(f"Fetching {symbol} {interval} ({source}, {args.days}d)...")
            df = fetch_historical(symbol, interval, args.days)
            out_path = out_dir / f"{symbol}_{interval}.csv"
            if df is None or df.empty:
                print(f"  WARNING: no data returned for {symbol} {interval} -- skipping")
                continue
            df.to_csv(out_path, index=False)
            print(f"  wrote {len(df)} candles -> {out_path}")

    print("Done.")


if __name__ == "__main__":
    main()
