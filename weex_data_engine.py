"""Public WEEX Contract V3 market-data adapter for TradFi perpetuals."""
from __future__ import annotations

import time
import requests
import pandas as pd

from logger import log

BASE = "https://api-contract.weex.com/capi/v3/market"
HEADERS = {"User-Agent": "QuantBot-WEEX-MultiAsset/1.0"}


def fetch_klines(symbol: str, interval: str = "1h", limit: int = 300):
    params = {"symbol": symbol, "interval": interval, "limit": min(int(limit), 1000)}
    try:
        r = requests.get(f"{BASE}/klines", params=params, headers=HEADERS, timeout=15)
        r.raise_for_status()
        data = r.json()
        if not data:
            return None
        rows = []
        for x in data:
            rows.append({
                "open_time": int(x[0]), "open": float(x[1]), "high": float(x[2]),
                "low": float(x[3]), "close": float(x[4]), "volume": float(x[5]),
                "taker_buy_volume": float(x[9]) if len(x) > 9 else float(x[5]) * 0.5,
            })
        return pd.DataFrame(rows).sort_values("open_time").drop_duplicates("open_time").reset_index(drop=True)
    except (requests.RequestException, ValueError, TypeError, IndexError) as exc:
        log.warning("[WEEX %s %s] fetch failed: %s", symbol, interval, exc)
        return None


def fetch_history(symbol: str, interval: str = "15m", days: int = 60):
    """Paginate WEEX historyKlines (100 rows/request) backwards from now."""
    now = int(time.time() * 1000)
    interval_ms = {"1m": 60_000, "5m": 300_000, "15m": 900_000, "30m": 1_800_000, "1h": 3_600_000, "4h": 14_400_000, "12h": 43_200_000, "1d": 86_400_000}.get(interval)
    if not interval_ms:
        raise ValueError(f"Unsupported interval: {interval}")
    start = now - days * 86_400_000
    rows = []
    cursor = start
    while cursor < now:
        params = {"symbol": symbol, "interval": interval, "startTime": cursor, "endTime": now, "limit": 100, "priceType": "LAST"}
        try:
            r = requests.get(f"{BASE}/historyKlines", params=params, headers=HEADERS, timeout=15)
            r.raise_for_status()
            data = r.json() or []
            if not data:
                break
            data = sorted(data, key=lambda x: int(x[0]))
            rows.extend(data)
            last = int(data[-1][0])
            nxt = last + interval_ms
            time.sleep(0.15)
            if nxt <= cursor:
                break
            cursor = nxt
            if len(data) < 100:
                break
        except (requests.RequestException, ValueError, TypeError, IndexError) as exc:
            log.warning("[WEEX %s %s] history fetch failed: %s", symbol, interval, exc)
            return None
    if not rows:
        return None
    unique = {int(x[0]): x for x in rows}
    out = []
    for x in sorted(unique.values(), key=lambda z: int(z[0])):
        out.append({"open_time": int(x[0]), "open": float(x[1]), "high": float(x[2]), "low": float(x[3]), "close": float(x[4]), "volume": float(x[5]), "taker_buy_volume": float(x[9]) if len(x) > 9 else float(x[5]) * 0.5})
    return pd.DataFrame(out)


def fetch_funding_rate(symbol: str):
    try:
        r = requests.get(f"{BASE}/premiumIndex", params={"symbol": symbol}, headers=HEADERS, timeout=10)
        r.raise_for_status()
        data = r.json()
        if isinstance(data, list):
            data = data[0] if data else {}
        value = data.get("lastFundingRate")
        return (float(value), "weex", None) if value not in (None, "") else (None, None, "WEEX returned no funding rate")
    except (requests.RequestException, ValueError, TypeError, IndexError) as exc:
        return None, None, f"WEEX funding error: {exc}"
