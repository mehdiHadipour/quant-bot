"""Deterministic Smart-Money context layer.

No private exchange/API credentials are required. Whale/fundamental inputs are
optional sidecars. Missing external context is NEVER fabricated; it becomes
NEUTRAL and is logged in the decision payload.
"""
from __future__ import annotations
import json, os
from datetime import datetime, timezone
from pathlib import Path
from news_provider import fundamental_score as live_news_score


def _json_env(name: str):
    raw = os.getenv(name, "").strip()
    if not raw:
        return {}
    try:
        value = json.loads(raw)
        return value if isinstance(value, dict) else {}
    except (TypeError, ValueError):
        return {}


def _load_json_file(env_name: str):
    path = os.getenv(env_name, "").strip()
    if not path:
        return {}
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}


def _lookup(mapping, symbol):
    if not isinstance(mapping, dict):
        return {}
    value = mapping.get(symbol) or mapping.get(symbol.upper()) or mapping.get(symbol.replace("USDT", ""))
    return value if isinstance(value, dict) else {}


def _utc_hour(df):
    if df is None or df.empty:
        return datetime.now(timezone.utc).hour
    if "open_time" in df.columns:
        try:
            return datetime.fromtimestamp(float(df["open_time"].iloc[-1]) / 1000, tz=timezone.utc).hour
        except (TypeError, ValueError, OSError, OverflowError):
            pass
    return datetime.now(timezone.utc).hour


def session_context(df):
    h = _utc_hour(df)
    # UTC session windows; overlap gets highest quality, rollover gets lowest.
    if 13 <= h < 16:
        return {"name": "LONDON_NY_OVERLAP", "quality": 1.0, "allow": True}
    if 8 <= h < 13:
        return {"name": "LONDON", "quality": 0.85, "allow": True}
    if 16 <= h < 21:
        return {"name": "NEW_YORK", "quality": 0.90, "allow": True}
    if 0 <= h < 8:
        return {"name": "ASIA", "quality": 0.65, "allow": True}
    # Rollover is lower quality, but it is NOT a hard trading blackout.
    # The user requested continuous market coverage; quality is exposed to
    # the scoring layer instead of creating a dead period.
    return {"name": "ROLLOVER_LOW_LIQUIDITY", "quality": 0.35, "allow": True}


def footprint_proxy(df):
    """Best available OHLC/taker-flow proxy; explicitly not fake tick footprint."""
    if df is None or df.empty:
        return {"bias": "NEUTRAL", "strength": 0.0, "delta": 0.0, "absorption": False}
    row = df.iloc[-1]
    vol = float(row.get("volume", 0) or 0)
    taker = float(row.get("taker_buy_volume", vol * 0.5) or 0)
    ratio = taker / vol if vol > 0 else 0.5
    delta = 2.0 * ratio - 1.0
    o, h, l, c = map(float, (row["open"], row["high"], row["low"], row["close"]))
    rng = max(h - l, 1e-12)
    body = abs(c - o) / rng
    lower = min(o, c) - l
    upper = h - max(o, c)
    absorption = (delta < -0.20 and lower / rng > 0.35 and c > l + 0.55*rng) or (delta > 0.20 and upper / rng > 0.35 and c < l + 0.45*rng)
    if delta >= 0.12:
        bias = "BUY"
    elif delta <= -0.12:
        bias = "SELL"
    else:
        bias = "NEUTRAL"
    strength = min(1.0, abs(delta) * 2.5 + (0.25 if absorption else 0.0) + (0.15 if body > 0.55 else 0.0))
    return {"bias": bias, "strength": strength, "delta": delta, "absorption": absorption}


def external_context(symbol):
    whale = _lookup(_json_env("WHALE_BIAS_JSON") or _load_json_file("WHALE_BIAS_FILE"), symbol)
    fundamental = _lookup(_json_env("FUNDAMENTAL_JSON") or _load_json_file("FUNDAMENTAL_FILE"), symbol)
    wbias = str(whale.get("bias", "NEUTRAL")).upper()
    wconf = max(0.0, min(1.0, float(whale.get("confidence", 0) or 0)))
    try:
        fscore = max(-5.0, min(5.0, float(fundamental.get("score", 0) or 0)))
    except (TypeError, ValueError):
        fscore = 0.0
    if not fundamental and os.getenv("NEWS_ENABLED", "1").strip().lower() not in {"0", "false", "no", "off"}:
        # Live-only public RSS score. Historical tests/backtests should disable
        # NEWS_ENABLED or provide a timestamped sidecar to prevent look-ahead.
        fscore = max(-3.0, min(3.0, float(live_news_score(symbol))))
    return {"whale_bias": wbias if wbias in {"BUY", "SELL", "NEUTRAL"} else "NEUTRAL", "whale_confidence": wconf, "fundamental_score": fscore}


def evaluate(symbol, direction, df_1h, *, min_session_quality=0.0):
    fp = footprint_proxy(df_1h)
    sess = session_context(df_1h)
    ext = external_context(symbol)
    mode = os.getenv("SMART_CONTEXT_MODE", "live").strip().lower()
    session_veto = os.getenv("SESSION_VETO_ENABLED", "0").strip().lower() in {"1", "true", "yes", "on"}
    # External context is optional. It can only veto when supplied with real data.
    if fp["bias"] in {"BUY", "SELL"} and fp["strength"] >= 0.65 and fp["bias"] != direction:
        return False, {"reason": "Footprint/OrderFlow conflict", "footprint": fp, "session": sess, **ext}
    if ext["whale_confidence"] >= 0.70 and ext["whale_bias"] in {"BUY", "SELL"} and ext["whale_bias"] != direction:
        return False, {"reason": "Whale bias conflict", "footprint": fp, "session": sess, **ext}
    if (direction == "BUY" and ext["fundamental_score"] <= -3.0) or (direction == "SELL" and ext["fundamental_score"] >= 3.0):
        return False, {"reason": "Fundamental conflict", "footprint": fp, "session": sess, **ext}
    if session_veto and sess["quality"] < min_session_quality:
        return False, {"reason": "Low-liquidity session", "footprint": fp, "session": sess, **ext}
    # In live mode, a supplied strong aligned context adds confidence; absent data stays neutral.
    bonus = 0
    if fp["bias"] == direction and fp["strength"] >= 0.35: bonus += 1
    if ext["whale_bias"] == direction and ext["whale_confidence"] >= 0.50: bonus += 1
    if (direction == "BUY" and ext["fundamental_score"] > 1) or (direction == "SELL" and ext["fundamental_score"] < -1): bonus += 1
    return True, {"reason": "OK", "footprint": fp, "session": sess, "bonus": bonus, "mode": mode, **ext}
