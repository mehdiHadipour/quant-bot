"""Lightweight optional fundamental/news score from public Google News RSS.

The provider is intentionally conservative: on network/parser failure it returns
0 (neutral). It never turns missing news into a bullish/bearish opinion.
Set NEWS_ENABLED=0 to disable. Historical backtests should keep it disabled or
use a timestamped news sidecar to avoid look-ahead bias.
"""
from __future__ import annotations
import re, time, xml.etree.ElementTree as ET
import requests

_CACHE = {}
_POS = ("etf", "approval", "partnership", "adoption", "upgrade", "launch", "inflow", "record", "bullish")
_NEG = ("hack", "exploit", "lawsuit", "ban", "fraud", "outflow", "delist", "liquidation", "bearish")

def fundamental_score(symbol: str, now_ts=None) -> float:
    import os
    if os.getenv('SMART_CONTEXT_MODE', 'live').strip().lower() == 'backtest':
        return 0.0
    if str(os.getenv('NEWS_ENABLED', '1')).strip().lower() in {'0','false','no','off'}:
        return 0.0
    now = now_ts or time.time()
    cached = _CACHE.get(symbol)
    if cached and now - cached[0] < 600:
        return cached[1]
    base = symbol.replace('USDT','').replace('USD','')
    url = 'https://news.google.com/rss/search'
    try:
        r = requests.get(url, params={'q': f'{base} crypto', 'hl':'en-US', 'gl':'US', 'ceid':'US:en'}, timeout=8,
                         headers={'User-Agent':'QuantBot/28.0'})
        r.raise_for_status()
        root = ET.fromstring(r.content)
        titles=[]
        for item in root.findall('.//item')[:20]:
            title=item.findtext('title') or ''
            titles.append(re.sub(r'\s+',' ',title).lower())
        pos=sum(any(k in t for k in _POS) for t in titles)
        neg=sum(any(k in t for k in _NEG) for t in titles)
        # Small bounded score; news is a filter, never a standalone signal.
        score=max(-3.0,min(3.0, float(pos-neg)))
    except (requests.RequestException, ET.ParseError, ValueError, TypeError):
        score=0.0
    _CACHE[symbol]=(now,score)
    return score
