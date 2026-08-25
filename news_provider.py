"""Optional, cached fundamental-news provider.

Uses GDELT's public article search when enabled. It is intentionally optional:
network failure, empty results, or rate limits return no headlines and never
create a trade. Backtests do not call this module, preventing look-ahead.
"""
from __future__ import annotations
import time, requests
from logger import log

GDELT_URL = "https://api.gdeltproject.org/api/v2/doc/doc"
_CACHE = {}
CACHE_SECONDS = 900


def fetch_headlines(symbol: str, max_records: int = 12):
    base = symbol.replace("USDT", "")
    if not base:
        return []
    now = time.time()
    cached = _CACHE.get(base)
    if cached and now - cached[0] < CACHE_SECONDS:
        return list(cached[1])
    params = {
        "query": f'"{base}" cryptocurrency',
        "mode": "ArtList",
        "format": "json",
        "maxrecords": max_records,
        "timespan": "6h",
        "sort": "HybridRel",
    }
    try:
        r = requests.get(GDELT_URL, params=params, timeout=8)
        if r.status_code != 200:
            return []
        data = r.json()
        articles = data.get("articles", []) if isinstance(data, dict) else []
        headlines = [a.get("title", "") for a in articles if a.get("title")]
        _CACHE[base] = (now, headlines)
        return headlines
    except (requests.RequestException, ValueError, TypeError) as exc:
        log.warning(f"[fundamental {symbol}] news unavailable: {exc}")
        return []
