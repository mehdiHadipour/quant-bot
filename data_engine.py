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
                        return pd.DataFrame([{
                            "close": float(x[4]),
                            "high": float(x[2]),
                            "low": float(x[3]),
                            "volume": float(x[5]),
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
