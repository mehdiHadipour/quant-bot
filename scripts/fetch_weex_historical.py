"""
Downloads historical OHLCV candles from WEEX's public contract market-data
endpoint for backtesting the commodity/TradFi symbols (XAUUSDT, XAGUSDT,
CLUSDT, NATGASUSDT) — the crypto equivalent is
scripts/fetch_historical_klines.py (Binance).

BUG FIX (found while reviewing why a commodity backtest would fail): this
script previously wrote CSVs with NO taker_buy_volume column, but
indicators.py accesses df['taker_buy_volume'] unconditionally on every
call — so any backtest run against this script's old output would crash
with a KeyError the moment it reached a real signal check, not just
produce a slightly-off result. Fixed by adding taker_buy_volume=0.0 to
every row, matching data_engine.py's fetch_weex_klines() (WEEX's public
endpoint doesn't expose a taker-buy split, so live fetches already used
this same neutral placeholder — analyze_market()'s order-flow scoring
already treats current_volume==0 or an exact 50/50 buy_ratio as "no
opinion" for that factor, so this degrades gracefully rather than
fabricating a number).

Also brought up to parity with fetch_historical_klines.py: loops over all
4 intervals by default instead of requiring 4 separate invocations, and
adds the same --warmup-days concept (indicators.MIN_CANDLES=210 means the
requested test window needs 210+ candles of REAL history before it starts,
or the first stretch of any backtest will be silently degraded/skipped).

NOTE ON THE ENDPOINT: this script calls WEEX's historyKlines endpoint
(paginated, for a full date range), while data_engine.py's live
fetch_weex_klines() calls the plain klines endpoint (most-recent-N,
no pagination) — analogous to fetch_historical_klines.py vs.
data_engine.fetch_klines() for Binance. Both are documented WEEX
endpoints for different purposes; this could not be verified against
WEEX's live API in the environment this fix was written in (no network
access there), so double-check the first run's output looks sane
(reasonable prices, no gaps) before trusting a full backtest on it.

USAGE:
    python scripts/fetch_weex_historical.py --symbols XAUUSDT,XAGUSDT,CLUSDT,NATGASUSDT --days 180

Then run scripts/run_backtest.py against the downloaded data, exactly as
with the Binance-fetched crypto CSVs — same file naming convention
({symbol}_{interval}.csv), same required columns, so a single
run_backtest.py call can mix crypto and commodity symbols together as
long as both scripts have been run into the same --out-dir/--data-dir.
"""
import argparse
import os
import sys
import time
import requests
import pandas as pd

WEEX_HISTORY_URL = "https://api-contract.weex.com/capi/v3/market/historyKlines"

INTERVAL_MS = {
    "15m": 15 * 60 * 1000,
    "1h": 60 * 60 * 1000,
    "4h": 4 * 60 * 60 * 1000,
    "1d": 24 * 60 * 60 * 1000,
}


def fetch_paginated(symbol, interval, start_ms, end_ms):
    """Walks the full [start_ms, end_ms) range in <=100-candle batches
    (WEEX's per-request cap, smaller than Binance's 1000)."""
    all_rows = []
    cursor = start_ms
    while cursor < end_ms:
        params = {"symbol": symbol, "interval": interval, "limit": 100, "startTime": cursor, "endTime": end_ms}
        try:
            resp = requests.get(WEEX_HISTORY_URL, params=params, timeout=20)
            if resp.status_code != 200:
                print(f"    ⚠️ HTTP {resp.status_code} for the batch starting {cursor} — stopping here "
                      f"(partial data will still be saved)")
                break
            batch = resp.json()
        except (requests.RequestException, ValueError) as e:
            print(f"    ⚠️ {e} for the batch starting {cursor} — stopping here (partial data will still be saved)")
            break

        if not batch:
            break
        for x in batch:
            # WEEX kline array: [0]=open time [1]=open [2]=high [3]=low
            # [4]=close [5]=volume — no taker-buy split available, see
            # module docstring for why 0.0 here is the correct neutral
            # placeholder rather than a workaround.
            all_rows.append({
                "close_time": int(x[0]),
                "open": float(x[1]), "high": float(x[2]), "low": float(x[3]),
                "close": float(x[4]), "volume": float(x[5]),
                "taker_buy_volume": 0.0,
            })
        if len(batch) < 100:
            break
        cursor = int(batch[-1][0]) + 1
        if cursor >= end_ms:
            break
        time.sleep(0.15)  # be polite to the free public endpoint

    return pd.DataFrame(all_rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--symbols", required=True, help="Comma-separated, e.g. XAUUSDT,XAGUSDT,CLUSDT,NATGASUSDT")
    parser.add_argument("--days", type=int, default=180, help="How many days of history to fetch")
    parser.add_argument("--intervals", default="15m,1h,4h,1d")
    parser.add_argument("--out-dir", default="backtest_data")
    parser.add_argument(
        "--warmup-days", type=int, default=220,
        help="Extra calendar days fetched BEFORE the requested test window, so slow "
             "indicators (e.g. a 1D EMA200 / the bot's 210-candle minimum) have enough "
             "real history by the time the actual test period begins. Must exceed "
             "indicators.MIN_CANDLES (210); default has margin.",
    )
    args = parser.parse_args()

    end_ms = int(time.time() * 1000)
    start_ms = end_ms - (args.days + args.warmup_days) * 24 * 60 * 60 * 1000
    os.makedirs(args.out_dir, exist_ok=True)

    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    intervals = [i.strip() for i in args.intervals.split(",") if i.strip()]

    for symbol in symbols:
        for interval in intervals:
            if interval not in INTERVAL_MS:
                print(f"⚠️ skipping unknown interval '{interval}' (expected one of {list(INTERVAL_MS)})")
                continue
            print(f"Fetching {symbol} {interval} for the last {args.days} days (+{args.warmup_days} warmup)...")
            df = fetch_paginated(symbol, interval, start_ms, end_ms)
            if df.empty:
                print(f"  ❌ got NO data for {symbol} {interval} — skipping (see warnings above; "
                      f"double check {symbol} is a real WEEX contract symbol)")
                continue
            path = os.path.join(args.out_dir, f"{symbol}_{interval}.csv")
            df.sort_values("close_time").to_csv(path, index=False)
            print(f"  ✅ saved {len(df)} candles -> {path}")

    print("\nDone. Next: python scripts/run_backtest.py --symbols " + args.symbols)


if __name__ == "__main__":
    sys.exit(main())
