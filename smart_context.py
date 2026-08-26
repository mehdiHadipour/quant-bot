"""Smart-money/context filters for Quant Bot V27.30.

All features are deterministic when historical data is supplied. External
whale/news inputs are optional and fail neutral; they never create a signal
on their own. This avoids look-ahead and keeps backtests reproducible.
"""
from __future__ import annotations
import json, os, re
from datetime import datetime, timezone
import pandas as pd

POSITIVE_NEWS = re.compile(r"\b(etf|approval|approved|partnership|upgrade|launch|adoption|inflow|buyback|listing|mainnet)\b", re.I)
NEGATIVE_NEWS = re.compile(r"\b(hack|exploit|lawsuit|ban|delist|outflow|liquidation|bankrupt|breach|vulnerability|shutdown)\b", re.I)


def session_context(ts=None):
    """Return a small quality score based on UTC global-market sessions."""
    if ts is None:
        ts = datetime.now(timezone.utc)
    ts = pd.Timestamp(ts)
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    else:
        ts = ts.tz_convert("UTC")
    h = ts.hour + ts.minute / 60
    weekend = ts.weekday() >= 5
    if 13 <= h < 16:  # London/NY overlap
        return {"score": 2, "session": "LONDON_NY_OVERLAP", "weekend": weekend}
    if 8 <= h < 13:
        return {"score": 1, "session": "LONDON", "weekend": weekend}
    if 16 <= h < 21:
        return {"score": 1, "session": "NEW_YORK", "weekend": weekend}
    if 0 <= h < 8:
        return {"score": -1, "session": "ASIA", "weekend": weekend}
    return {"score": -2, "session": "OFF_HOURS", "weekend": weekend}


def _direction_sign(direction):
    return 1 if direction == "BUY" else -1


def pullback_score(df_1h, direction):
    """Prefer entries after a controlled pullback instead of an extended chase."""
    if df_1h is None or len(df_1h) < 55:
        return 0, "no-pullback-data"
    close = float(df_1h.close.iloc[-1])
    ema20 = float(df_1h.close.ewm(span=20, adjust=False).mean().iloc[-1])
    ema50 = float(df_1h.close.ewm(span=50, adjust=False).mean().iloc[-1])
    atr = float((df_1h.high - df_1h.low).rolling(14).mean().iloc[-1])
    if atr <= 0:
        return 0, "no-atr"
    dist20 = abs(close - ema20) / atr
    sign = _direction_sign(direction)
    aligned = sign * (close - ema20) >= 0
    near = dist20 <= 1.25
    trend_zone = sign * (ema20 - ema50) > 0
    if aligned and near and trend_zone:
        return 2, "controlled-pullback"
    if aligned and dist20 <= 2.25 and trend_zone:
        return 1, "acceptable-pullback"
    if dist20 > 2.75:
        return -2, "extended-entry"
    return 0, "neutral-entry-location"


def candle_orderflow_score(df_1h, direction):
    """Historical-safe footprint proxy from taker-buy ratio + rejection.
    Live code can replace this with real agg-trade footprint metrics."""
    if df_1h is None or len(df_1h) < 20:
        return 0, "no-orderflow-data"
    row = df_1h.iloc[-1]
    vol = float(row.volume)
    taker = float(row.taker_buy_volume) if "taker_buy_volume" in df_1h else vol * .5
    ratio = taker / vol if vol > 0 else .5
    body = abs(float(row.close) - float(row.open))
    upper = float(row.high) - max(float(row.open), float(row.close))
    lower = min(float(row.open), float(row.close)) - float(row.low)
    score = 0
    if direction == "BUY" and ratio >= .56:
        score += 1
    elif direction == "SELL" and ratio <= .44:
        score += 1
    elif (direction == "BUY" and ratio <= .42) or (direction == "SELL" and ratio >= .58):
        score -= 2
    if direction == "BUY" and lower > 1.5 * max(body, 1e-9):
        score += 1
    if direction == "SELL" and upper > 1.5 * max(body, 1e-9):
        score += 1
    if direction == "BUY" and upper > 2 * max(body, 1e-9) and ratio < .5:
        score -= 1
    if direction == "SELL" and lower > 2 * max(body, 1e-9) and ratio > .5:
        score -= 1
    return max(-2, min(2, score)), f"taker_ratio={ratio:.2f}"


def footprint_metrics_score(metrics, direction):
    if not metrics:
        return None, "no-live-footprint"
    ratio = float(metrics.get("buy_ratio", .5))
    s = 1 if direction == "BUY" else -1
    score = 0
    if s * (ratio - .5) >= .08:
        score += 2
    elif s * (ratio - .5) <= -.12:
        score -= 2
    # Absorption proxy: aggressive flow at the opposite extreme with price
    # rejection is favorable to the reversal direction.
    low = metrics.get("imbalance_near_low")
    high = metrics.get("imbalance_near_high")
    if direction == "BUY" and low is not None and low < .40:
        score += 1
    if direction == "SELL" and high is not None and high > .60:
        score += 1
    return max(-3, min(3, score)), f"live_buy_ratio={ratio:.2f}"


def load_whale_bias(symbol, direction):
    """Optional Hyperdash-export bridge.

    Reads JSON from WHALE_BIAS_FILE or WHALE_BIAS_JSON. Expected shape:
    {"SOLUSDT": {"long": 0.7, "short": 0.3, "quality": 0.8}}
    No public Hyperdash API is assumed or fabricated; absent data is neutral.
    """
    raw = os.getenv("WHALE_BIAS_JSON", "").strip()
    path = os.getenv("WHALE_BIAS_FILE", "").strip()
    if not raw and path:
        try:
            with open(path, "r", encoding="utf-8") as f:
                raw = f.read()
        except OSError:
            return 0, "whale-data-unavailable"
    if not raw:
        return 0, "whale-data-unavailable"
    try:
        data = json.loads(raw)
        item = data.get(symbol, {})
        long_p = float(item.get("long", 0.5)); short_p = float(item.get("short", 0.5))
        quality = max(0.0, min(1.0, float(item.get("quality", 1.0))))
        bias = (long_p - short_p) * _direction_sign(direction)
        if bias >= .25:
            return round(2 * quality), "whale-aligned"
        if bias <= -.25:
            return -round(2 * quality), "whale-opposed"
        return 0, "whale-neutral"
    except (ValueError, TypeError, json.JSONDecodeError):
        return 0, "whale-data-invalid"


def fundamental_score(symbol, direction, headlines=None):
    """Score supplied headlines. No historical backtest leakage: backtests
    pass no headlines, so this returns neutral."""
    if not headlines:
        return 0, "fundamental-data-unavailable"
    text = " ".join(str(x) for x in headlines if x)
    pos = len(POSITIVE_NEWS.findall(text)); neg = len(NEGATIVE_NEWS.findall(text))
    raw = max(-3, min(3, pos - neg))
    # Broad crypto news is not inherently directional for every coin; only
    # strong negative news is allowed to hard-veto via config in the caller.
    return raw * _direction_sign(direction), f"news_pos={pos},news_neg={neg}"


def smart_context(df_15m, df_1h, direction, *, footprint_metrics=None, timestamp=None, whale_score=0, fundamental_score_value=0):
    pscore, preason = pullback_score(df_1h, direction)
    live_score, freason = footprint_metrics_score(footprint_metrics, direction)
    if live_score is None:
        live_score, freason = candle_orderflow_score(df_1h, direction)
    sess = session_context(timestamp)
    total = pscore + live_score + sess["score"] + int(whale_score) + int(fundamental_score_value)
    return {
        "score": total,
        "pullback_score": pscore,
        "footprint_score": live_score,
        "session_score": sess["score"],
        "whale_score": int(whale_score),
        "fundamental_score": int(fundamental_score_value),
        "session": sess["session"],
        "weekend": sess["weekend"],
        "reasons": [preason, freason],
    }
