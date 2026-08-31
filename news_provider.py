"""Lightweight optional fundamental/news score from public Google News RSS.

The provider is intentionally conservative: on network/parser failure it returns
0 (neutral). It never turns missing news into a bullish/bearish opinion.
Set NEWS_ENABLED=0 to disable. Historical backtests should keep it disabled or
use a timestamped news sidecar to avoid look-ahead bias.
"""
from __future__ import annotations
import re, time, xml.etree.ElementTree as ET
from datetime import datetime, timezone
import requests

_CACHE = {}
_POS = ("etf", "approval", "partnership", "adoption", "upgrade", "launch", "inflow", "record", "bullish")
_NEG = ("hack", "exploit", "lawsuit", "ban", "fraud", "outflow", "delist", "liquidation", "bearish")
_HIGH_IMPACT = ("fomc", "fed rate", "interest rate", "cpi", "nfp", "nonfarm", "ppi", "gdp", "ecb", "boe", "rate decision", "sec", "etf approval", "etf rejection", "hack", "exploit", "bankruptcy")

def news_context(symbol: str, now_ts=None, block_minutes=30):
    """Return (score, recent_high_impact, latest_age_minutes).

    The RSS feed is live-only. Publication timestamps are read from the feed so
    a recent high-impact headline can activate the configured news blackout.
    Missing/invalid timestamps never create a false block.
    """
    if str(__import__('os').getenv('NEWS_ENABLED', '1')).strip().lower() in {'0','false','no','off'}:
        return 0.0, False, None
    now = now_ts or time.time()
    cached = _CACHE.get((symbol, 'context'))
    if cached and now - cached[0] < 600:
        return cached[1], cached[2], cached[3]
    base = symbol.replace('USDT','').replace('USD','')
    url = 'https://news.google.com/rss/search'
    try:
        r = requests.get(url, params={'q': f'{base} crypto', 'hl':'en-US', 'gl':'US', 'ceid':'US:en'}, timeout=8,
                         headers={'User-Agent':'QuantBot/30.1'})
        r.raise_for_status()
        root = ET.fromstring(r.content)
        titles=[]; ages=[]; recent_impact=False
        for item in root.findall('.//item')[:20]:
            title=(item.findtext('title') or '').lower()
            titles.append(re.sub(r'\s+',' ',title))
            pub=item.findtext('pubDate') or ''
            try:
                dt=datetime.strptime(pub, '%a, %d %b %Y %H:%M:%S %Z').replace(tzinfo=timezone.utc)
                age=max(0.0,(now-dt.timestamp())/60.0)
                ages.append(age)
                if block_minutes > 0 and age <= block_minutes and any(k in title for k in _HIGH_IMPACT):
                    recent_impact=True
            except (ValueError, TypeError):
                pass
        pos=sum(any(k in t for k in _POS) for t in titles)
        neg=sum(any(k in t for k in _NEG) for t in titles)
        score=max(-3.0,min(3.0,float(pos-neg)))
        latest=min(ages) if ages else None
    except (requests.RequestException, ET.ParseError, ValueError, TypeError):
        score=0.0; recent_impact=False; latest=None
    _CACHE[(symbol, 'context')]=(now,score,recent_impact,latest)
    return score,recent_impact,latest


def fundamental_score(symbol: str, now_ts=None) -> float:
    if str(__import__('os').getenv('NEWS_ENABLED', '1')).strip().lower() in {'0','false','no','off'}:
        return 0.0
    score, _, _ = news_context(symbol, now_ts=now_ts, block_minutes=0)
    return score
