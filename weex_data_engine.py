"""Klines for WEEX "TradFi" tokenized products (gold, silver, tokenized US
stocks) via WEEX's public, unauthenticated spot market-data API.

Endpoint and response shape are exactly as published in WEEX's own API docs
(https://www.weex.com/api-doc/spot/MarketDataAPI/GetKLineData):

    GET https://api-spot.weex.com/api/v3/market/klines
        ?symbol=<SYMBOL>&interval=<INTERVAL>&limit=<N>

Each returned kline is [open_time_ms, open, high, low, close, volume,
close_time_ms, quote_volume, trade_count, taker_buy_base_volume,
taker_buy_quote_volume] -- the same fields, in the same order, as
Binance's kline endpoint -- so this returns the identical DataFrame shape
as data_engine.fetch_klines() and slots into the existing analyze_market()
pipeline with zero changes there.

Important, honest caveats:
  - These are TOKENIZED/synthetic instruments (e.g. XAUT/PAXG track gold's
    price, NVDAUSDT tracks NVIDIA's stock price) settled in USDT on WEEX --
    not the underlying spot commodity or equity itself.
  - This uses WEEX's SPOT market data for these symbols. WEEX also lists
    many of them as leveraged perpetual futures under a separate contract
    API with different symbol formatting; that is NOT wired in here. Spot
    price action for a liquid tokenized instrument tracks its perpetual
    closely, so this is a reasonable and much simpler starting point, but
    it is not literally the futures order book.
  - WEEX's public docs list no forex (currency-pair) products and no oil/
    gas ticker was visible in what was shared, so none are hard-coded here.
    Add real, confirmed ticker strings to config.WEEX_SYMBOLS if/when you
    have them -- guessing a ticker that doesn't exist would just make that
    symbol fail to fetch every cycle.
"""
import time
import requests
import pandas as pd

from logger import log

BASE_URL = "https://api-spot.weex.com/api/v3/market/klines"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; AIQuantBot/1.0)"}


def fetch_klines(symbol, interval="1h", limit=300):
    """Same contract as data_engine.fetch_klines(): returns a DataFrame with
    columns [open_time, open, high, low, close, volume, taker_buy_volume],
    or None on failure (never raises).
    """
    tag = f"WEEX {symbol} {interval}"
    params = {"symbol": symbol, "interval": interval, "limit": limit}

    for attempt in range(3):
        try:
            resp = requests.get(BASE_URL, params=params, headers=HEADERS, timeout=15)
            if resp.status_code == 200:
                data = resp.json()
                if data:
                    return pd.DataFrame([{
                        "open_time": int(x[0]),
                        "open": float(x[1]),
                        "high": float(x[2]),
                        "low": float(x[3]),
                        "close": float(x[4]),
                        "volume": float(x[5]),
                        "taker_buy_volume": float(x[9]),
                    } for x in data])
                log.warning(f"[{tag}] WEEX returned an empty kline list")
                return None
            elif resp.status_code in (403, 429):
                log.warning(f"[{tag}] WEEX returned {resp.status_code}, backing off...")
                time.sleep(2)
            else:
                log.warning(f"[{tag}] WEEX returned status {resp.status_code}")
                time.sleep(1)
        except requests.RequestException as e:
            log.warning(f"[{tag}] Request error (attempt {attempt + 1}/3): {e}")
            time.sleep(1)

    log.error(f"[{tag}] Failed to fetch WEEX data after 3 attempts")
    return None
