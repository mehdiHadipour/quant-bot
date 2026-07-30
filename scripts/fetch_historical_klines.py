"""
Downloads historical OHLCV candles from Binance's public spot klines
endpoint for backtesting, with pagination (Binance caps each request at
1000 candles) and rate-limit backoff. Saves one CSV per symbol/interval
under backtest_data/.

This is a separate, occasional data-download tool — NOT something the
live bot ever calls. data_engine.py's fetch_klines() is optimized for
"give me the most recent N candles right now" (what the live bot needs
every cycle); this script is optimized for "give me a full historical
date range" (what a backtest needs once). Kept deliberately separate so
neither one's requirements compromise the other's simplicity.

USAGE:
    python scripts/fetch_historical_klines.py --symbols BTCUSDT,ETHUSDT --days 180

Then run scripts/run_backtest.py against the downloaded data.
"""
import argparse
import os
import sys
import time
import requests
import pandas as pd

# Same fallback host list as data_engine.py, for the same reason (the
# primary host is sometimes geo-blocked depending on where this runs).
BASE_URLS = [
    "https://data-api.binance.vision/api/v3/klines",
    "https://api.binance.com/api/v3/klines",
    "https://api1.binance.com/api/v3/klines",
    "https://api3.binance.com/api/v3/klines",
]

INTERVAL_MS = {
    "15m": 15 * 60 * 1000,
    "1h": 60 * 60 * 1000,
    "4h": 4 * 60 * 60 * 1000,
    "1d": 24 * 60 * 60 * 1000,
}


def fetch_one_batch(symbol, interval, start_ms, end_ms):
    """One paginated request (up to 1000 candles). Returns the raw
    Binance kline array, or None if every host failed."""
    params = {
        "symbol": symbol, "interval": interval,
        "startTime": start_ms, "endTime": end_ms, "limit": 1000,
    }
    for base_url in BASE_URLS:
        try:
            resp = requests.get(base_url, params=params, timeout=15)
            if resp.status_code == 200:
                return resp.json()
            if resp.status_code in (403, 418, 429):
                time.sleep(2)  # rate-limited — brief backoff, try next host
            # 451 (geo-blocked) or anything else: just try the next host.
        except requests.RequestException:
            continue
    return None


def fetch_paginated(symbol, interval, start_ms, end_ms):
    """Walks the full [start_ms, end_ms) range in <=1000-candle batches."""
    all_rows = []
    cursor = start_ms
    batch_span_ms = INTERVAL_MS[interval] * 1000  # ~1000 candles per request

    while cursor < end_ms:
        batch_end = min(cursor + batch_span_ms, end_ms)
        data = fetch_one_batch(symbol, interval, cursor, batch_end)
        if not data:
            print(f"    ⚠️ no data for the batch starting {cursor} — stopping here "
                  f"(partial data will still be saved)")
            break
        for x in data:
            # Binance kline array: [0]=open time [1]=open [2]=high [3]=low
            # [4]=close [5]=volume [6]=close time [9]=taker buy base volume
            all_rows.append({
                "close_time": int(x[6]),
                "open": float(x[1]), "high": float(x[2]), "low": float(x[3]),
                "close": float(x[4]), "volume": float(x[5]),
                "taker_buy_volume": float(x[9]),
            })
        if len(data) < 2:
            break
        cursor = int(data[-1][6]) + 1  # resume right after this batch's last close
        time.sleep(0.25)  # be polite to the free public endpoint

    return pd.DataFrame(all_rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbols", required=True, help="Comma-separated, e.g. BTCUSDT,ETHUSDT")
    parser.add_argument("--days", type=int, default=180, help="How many days of history to fetch")
    parser.add_argument("--intervals", default="15m,1h,4h,1d")
    parser.add_argument("--out-dir", default="backtest_data")
    parser.add_argument(
        "--warmup-days", type=int, default=220,
        help="Extra calendar days fetched BEFORE the requested test window, "
             "so slow indicators (e.g. a 1D EMA200 / the bot's 210-candle "
             "minimum for daily-timeframe confirmation) have enough real "
             "history by the time the actual test period begins. Must "
             "exceed indicators.MIN_CANDLES (210); default has margin.",
    )
    args = parser.parse_args()

    end_ms = int(time.time() * 1000)
    start_ms = end_ms - (args.days + args.warmup_days) * 24 * 60 * 60 * 1000
    os.makedirs(args.out_dir, exist_ok=True)

    symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]
    intervals = [i.strip() for i in args.intervals.split(",") if i.strip()]

    for symbol in symbols:
        for interval in intervals:
            if interval not in INTERVAL_MS:
                print(f"⚠️ skipping unknown interval '{interval}' (expected one of {list(INTERVAL_MS)})")
                continue
            print(f"Fetching {symbol} {interval} for the last {args.days} days...")
            df = fetch_paginated(symbol, interval, start_ms, end_ms)
            if df.empty:
                print(f"  ❌ got NO data for {symbol} {interval} — skipping (see warnings above)")
                continue
            path = os.path.join(args.out_dir, f"{symbol}_{interval}.csv")
            df.to_csv(path, index=False)
            print(f"  ✅ saved {len(df)} candles -> {path}")

    print("\nDone. Next: python scripts/run_backtest.py --symbols " + args.symbols)


if __name__ == "__main__":
    sys.exit(main())
