import requests
import pandas as pd
import time

from logger import log

# GitHub Actions runners are hosted in US datacenters, and api.binance.com
# sometimes returns HTTP 451 (geo-blocked) from those IPs. data-api.binance.vision
# is Binance's official unauthenticated market-data mirror and is not subject to
# that block, so it's tried first; the others are kept as fallbacks.
BASE_URLS = [
    "https://data-api.binance.vision/api/v3/klines",
    "https://api.binance.com/api/v3/klines",
    "https://api1.binance.com/api/v3/klines",
    "https://api2.binance.com/api/v3/klines",
    "https://api3.binance.com/api/v3/klines",
]

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; AIQuantBot/1.0)"}


def fetch_klines(symbol, interval="1h", limit=300):
    # Fetches now run concurrently across symbols (see main.fetch_all_klines),
    # so every log line is tagged with "symbol interval" — otherwise
    # interleaved output from parallel threads would be unreadable,
    # especially on a small mobile screen viewing the Actions log.
    tag = f"{symbol} {interval}"
    params = {"symbol": symbol, "interval": interval, "limit": limit}

    for base_url in BASE_URLS:
        for attempt in range(3):
            try:
                resp = requests.get(base_url, params=params, headers=HEADERS, timeout=15)
                if resp.status_code == 200:
                    data = resp.json()
                    if data:
                        # Binance's kline array has more than OHLCV:
                        # [0]=open time [1]=open [2]=high [3]=low [4]=close
                        # [5]=volume [6]=close time [7]=quote volume
                        # [8]=trade count [9]=taker buy base volume [10]=taker
                        # buy quote volume [11]=ignore.
                        # "Taker buy volume" is how much of the candle's
                        # volume came from aggressive market-buy orders
                        # (hitting the ask) vs. passive/sell-side volume —
                        # a real, free proxy for order-flow/buy-sell
                        # pressure without needing tick-level trade data.
                        return pd.DataFrame([{
                            "open": float(x[1]),
                            "high": float(x[2]),
                            "low": float(x[3]),
                            "close": float(x[4]),
                            "volume": float(x[5]),
                            "taker_buy_volume": float(x[9]),
                        } for x in data])
                elif resp.status_code in (403, 418, 429):
                    # Rate limited / banned on this host — back off then try next host.
                    log.warning(f"[{tag}] {base_url} returned {resp.status_code}, backing off...")
                    time.sleep(2)
                elif resp.status_code == 451:
                    # Geo-blocked on this host, no point retrying it — jump to next host.
                    log.warning(f"[{tag}] {base_url} returned 451 (geo-blocked), trying next endpoint...")
                    break
                else:
                    log.warning(f"[{tag}] {base_url} returned status {resp.status_code}")
                    time.sleep(1)
            except requests.RequestException as e:
                log.warning(f"[{tag}] Request error on {base_url} (attempt {attempt + 1}/3): {e}")
                time.sleep(1)

    log.error(f"[{tag}] Failed to fetch data from all endpoints")
    return None


# Funding rate is a free, public number from perpetual futures markets
# (no API key needed) that reflects how crowded/expensive it currently is
# to be long vs. short. It's a genuine, widely-used positioning/sentiment
# signal — not a fabricated data source — and costs nothing extra to fetch.
#
# PRIMARY SOURCE — Binance USDT-M futures: unlike spot market data (which
# has the data-api.binance.vision unblocked mirror used above), Binance's
# derivatives/futures API (fapi.binance.com) does not have a documented,
# free, unblocked mirror. Regulatory geo-restrictions on leveraged
# derivatives trading tend to be stricter than on spot, and in practice
# this endpoint returns HTTP 451 from GitHub Actions' US-based runner
# IPs consistently, not just occasionally.
#
# FALLBACK SOURCE — Bybit's public v5 market-data endpoint (added
# v25.4): a different exchange's number, not Binance's — very close in
# practice (perp funding rates across major USDT-margined venues track
# each other closely via cross-exchange arbitrage) but not identical, so
# treat it as "market consensus funding", not "Binance's exact number".
# This is a public, unauthenticated, read-only market-data call — the
# same kind of request anyone's browser makes loading Bybit's website,
# no account or trading involved — used purely because Binance's futures
# endpoint is geo-blocked from GitHub's IP range; it does not bypass or
# spoof anything about Bybit's own access rules.
#
# The feature fails open either way (funding_score stays 0, never blocks
# a signal) — and logging a full WARNING for every one of the 10 symbols
# on every single 5-minute cycle would be noise, so per-symbol failures
# only log at DEBUG (off by default) and the caller in main.py reports
# one aggregated line per cycle instead.
FUNDING_URL = "https://fapi.binance.com/fapi/v1/premiumIndex"
FUNDING_URL_FALLBACK = "https://api.bybit.com/v5/market/tickers"


def fetch_funding_rate(symbol):
    """Return (rate, source) for `symbol`. rate is a float (e.g. 0.0001 =
    0.01% per 8h) or None if it can't be fetched from either source —
    callers must treat None as "no opinion", never as 0.0, since a real
    0.0 and a failed fetch mean very different things. source is
    "binance", "bybit", or None, so callers/messages can be honest about
    which exchange's number this actually is when the fallback fires.
    """
    try:
        resp = requests.get(
            FUNDING_URL, params={"symbol": symbol}, headers=HEADERS, timeout=10
        )
        if resp.status_code == 200:
            data = resp.json()
            rate = data.get("lastFundingRate")
            if rate is not None:
                return float(rate), "binance"
        else:
            log.debug(f"[{symbol}] Binance funding rate returned {resp.status_code}, trying Bybit fallback...")
    except (requests.RequestException, ValueError, TypeError) as e:
        log.debug(f"[{symbol}] Binance funding rate failed: {e}, trying Bybit fallback...")

    try:
        resp = requests.get(
            FUNDING_URL_FALLBACK,
            params={"category": "linear", "symbol": symbol},
            headers=HEADERS,
            timeout=10,
        )
        if resp.status_code == 200:
            data = resp.json()
            ticker_list = (data.get("result") or {}).get("list") or []
            if ticker_list:
                rate = ticker_list[0].get("fundingRate")
                if rate not in (None, ""):
                    return float(rate), "bybit"
        else:
            log.debug(f"[{symbol}] Bybit funding rate fallback returned {resp.status_code}")
    except (requests.RequestException, ValueError, TypeError, IndexError) as e:
        log.debug(f"[{symbol}] Bybit funding rate fallback failed: {e}")

    return None, None
