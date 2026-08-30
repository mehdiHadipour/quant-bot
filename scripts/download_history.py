#!/usr/bin/env python3
"""Bulk-download long-horizon Binance kline history into backtest_data/.

Why this exists: ict_full_backtest.py (run via scripts/run_backtest.py)
only reads whatever is already sitting in backtest_data/<SYMBOL>_15m.csv
-- it never fetches anything itself. The CSVs currently in that folder
only go back a handful of months (whatever was "supplied", per
README_V30_ICT_FULL_ICHIMOKU.md), which is fine for quick iteration but
not enough for a 2-year backtest. data_engine.fetch_klines() (used by
the live bot) only pulls the most recent `limit` candles in a single
call, so it can't backfill years of history either.

This script paginates Binance's public klines endpoint backwards in
1000-candle pages (the API's per-request max) until it reaches the
requested start date, for every symbol you ask for, and writes each
symbol out in the exact schema ict_full_backtest.py expects:
open_time, open, high, low, close, volume, taker_buy_volume.

Usage:
    python scripts/download_history.py --years 2
    python scripts/download_history.py --years 2 --symbols BTCUSDT,ETHUSDT
    python scripts/download_history.py --start 2023-01-01 --end 2025-01-01

Only 15m candles are downloaded by default because that's the only
timeframe ict_full_backtest.py's run() actually reads per symbol -- it
derives its own 4h/1D bias by resampling the 15m data internally
(see htf() in ict_full_backtest.py). Pass --interval to fetch a
different timeframe instead (e.g. for main.py's live 1h/4h/1d files),
but you cannot fetch multiple intervals in one run.

Rate limits: Binance's public klines endpoint allows ~1200 weight/min
per IP; a 15m/2yr pull is ~70 requests per symbol, so this sleeps
briefly between requests and between symbols to stay well under that
even for a full 14-symbol run. For 14 symbols x 2 years x 15m this is
roughly 1,000 requests total and can take a while -- expect single-digit
minutes, not seconds. Let it run to completion; it prints progress per
symbol so you can see it isn't stuck.
"""
from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from logger import log  # noqa: E402

# Same mirror-then-fallback list as data_engine.py: data-api.binance.vision
# is Binance's official unauthenticated market-data mirror and, unlike
# api.binance.com, isn't geo-blocked (HTTP 451) from US-hosted IPs such as
# GitHub Actions runners.
BASE_URLS = [
    "https://data-api.binance.vision/api/v3/klines",
    "https://api.binance.com/api/v3/klines",
    "https://api1.binance.com/api/v3/klines",
]
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; AIQuantBot-HistoryDownloader/1.0)"}

INTERVAL_MS = {
    "1m": 60_000, "3m": 180_000, "5m": 300_000, "15m": 900_000, "30m": 1_800_000,
    "1h": 3_600_000, "2h": 7_200_000, "4h": 14_400_000, "1d": 86_400_000,
}

DEFAULT_SYMBOLS = [
    "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT",
    "DOGEUSDT", "AVAXUSDT", "LINKUSDT", "DOTUSDT", "ZECUSDT", "SUIUSDT",
    "TONUSDT", "NEARUSDT",
]


def _fetch_page(symbol: str, interval: str, start_ms: int, end_ms: int):
    """One page (<=1000 candles) starting at start_ms, trying each mirror
    in turn -- mirrors data_engine.fetch_klines()'s fallback behavior."""
    params = {
        "symbol": symbol, "interval": interval,
        "startTime": start_ms, "endTime": end_ms, "limit": 1000,
    }
    for base_url in BASE_URLS:
        try:
            r = requests.get(base_url, params=params, headers=HEADERS, timeout=20)
            if r.status_code == 200:
                return r.json() or []
            if r.status_code == 451:
                continue  # geo-blocked on this host, try the next one
            log.warning(f"[{symbol} {interval}] {base_url} returned {r.status_code}, retrying...")
            time.sleep(1.5)
        except requests.RequestException as e:
            log.warning(f"[{symbol} {interval}] request error on {base_url}: {e}")
            time.sleep(1.5)
    return None


def download_symbol(symbol: str, interval: str, start_ms: int, end_ms: int) -> "pd.DataFrame":
    import pandas as pd

    interval_ms = INTERVAL_MS.get(interval)
    if not interval_ms:
        raise ValueError(f"Unsupported interval: {interval}")

    all_rows = []
    cursor = start_ms
    page = 0
    while cursor < end_ms:
        page += 1
        data = _fetch_page(symbol, interval, cursor, end_ms)
        if data is None:
            log.error(f"[{symbol}] page {page}: all endpoints failed, stopping here (partial data kept).")
            break
        if not data:
            break
        all_rows.extend(data)
        last_open = int(data[-1][0])
        nxt = last_open + interval_ms
        if nxt <= cursor:
            break
        cursor = nxt
        print(f"  {symbol}: page {page}, {len(all_rows)} candles so far, up to {datetime.fromtimestamp(last_open/1000, tz=timezone.utc):%Y-%m-%d}", flush=True)
        if len(data) < 1000:
            break
        time.sleep(0.25)  # stay well under Binance's public rate limit

    if not all_rows:
        return pd.DataFrame(columns=["open_time", "open", "high", "low", "close", "volume", "taker_buy_volume"])

    unique = {int(x[0]): x for x in all_rows}
    out = [
        {
            "open_time": int(x[0]), "open": float(x[1]), "high": float(x[2]),
            "low": float(x[3]), "close": float(x[4]), "volume": float(x[5]),
            "taker_buy_volume": float(x[9]),
        }
        for x in sorted(unique.values(), key=lambda z: int(z[0]))
    ]
    return pd.DataFrame(out)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--symbols", default=",".join(DEFAULT_SYMBOLS), help="Comma-separated symbols (default: the bot's default 14).")
    ap.add_argument("--interval", default="15m", choices=sorted(INTERVAL_MS), help="Kline interval (default: 15m, the only one ict_full_backtest.py reads).")
    ap.add_argument("--years", type=float, default=None, help="How many years back from now. Ignored if --start is given.")
    ap.add_argument("--start", default=None, help="Start date YYYY-MM-DD (UTC). Overrides --years.")
    ap.add_argument("--end", default=None, help="End date YYYY-MM-DD (UTC). Defaults to now.")
    ap.add_argument("--out-dir", default=str(ROOT / "backtest_data"), help="Output directory (default: backtest_data/).")
    args = ap.parse_args()

    end_dt = datetime.strptime(args.end, "%Y-%m-%d").replace(tzinfo=timezone.utc) if args.end else datetime.now(timezone.utc)
    if args.start:
        start_dt = datetime.strptime(args.start, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    else:
        years = args.years if args.years is not None else 2.0
        start_dt = end_dt - timedelta(days=365.25 * years)

    start_ms, end_ms = int(start_dt.timestamp() * 1000), int(end_dt.timestamp() * 1000)
    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"Downloading {args.interval} candles for {len(symbols)} symbol(s), {start_dt:%Y-%m-%d} -> {end_dt:%Y-%m-%d}\n")
    for i, sym in enumerate(symbols, 1):
        print(f"[{i}/{len(symbols)}] {sym}")
        df = download_symbol(sym, args.interval, start_ms, end_ms)
        if df.empty:
            log.error(f"[{sym}] no data downloaded -- leaving any existing file untouched.")
            continue
        path = out_dir / f"{sym}_{args.interval}.csv"
        df.to_csv(path, index=False)
        print(f"  saved {len(df)} rows -> {path}\n")
        time.sleep(0.5)  # brief pause between symbols

    print("Done. Run `python scripts/run_backtest.py` to backtest against this data.")


if __name__ == "__main__":
    main()
