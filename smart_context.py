"""Deterministic Smart-Money context layer.

No private exchange/API credentials are required. Whale/fundamental inputs are
optional sidecars. Missing external context is NEVER fabricated; it becomes
NEUTRAL and is logged in the decision payload.
"""
from __future__ import annotations
import json, os
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from pathlib import Path
import pandas as pd
from volume_profile import context as vp_context
from config import (
    ASIA_ENABLED, SESSION_WEIGHTS, STRICT_SYMBOLS, STRICT_MIN_HLI,
    STRICT_MIN_SCORE, NEGATIVE_SESSIONS, NEGATIVE_SESSION_MIN_HLI,
    NEGATIVE_SESSION_MIN_SCORE, gate_enabled
)
from news_provider import fundamental_score as live_news_score, news_context
from asset_universe import classify_symbol, is_tradfi_symbol


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


def _hhmm(v, default):
    try:
        h,m=str(v).split(":"); return int(h)*60+int(m)
    except Exception: return default

def _in_window(minutes, start, end):
    if start <= end: return start <= minutes < end
    return minutes >= start or minutes < end

def session_context(df):
    """Fully configurable, DST-aware session classifier shared by live/backtest."""
    if df is None or df.empty:
        return {"name":"OFF_SESSION","quality":0.0,"allow":False}
    try:
        from config import SESSION_CFG
        ts=float(df["open_time"].iloc[-1])/1000
        dt=datetime.fromtimestamp(ts,tz=timezone.utc)
        l=dt.astimezone(ZoneInfo("Europe/London")); n=dt.astimezone(ZoneInfo("America/New_York")); t=dt.astimezone(ZoneInfo("Asia/Tokyo"))
        def cfg(name, fallback):
            z=SESSION_CFG.get(name,{}) if isinstance(SESSION_CFG,dict) else {}
            return z if isinstance(z,dict) else fallback
        asia=cfg("ASIA",{"enabled":True,"start":"09:00","end":"18:00","weight":0.72})
        lon=cfg("LONDON",{"enabled":True,"start":"08:00","end":"17:00","weight":0.88})
        ny=cfg("NEW_YORK",{"enabled":True,"start":"08:00","end":"17:00","weight":0.92})
        a=_in_window(t.hour*60+t.minute,_hhmm(asia.get("start"),540),_hhmm(asia.get("end"),1080)) and bool(asia.get("enabled",True))
        lo=_in_window(l.hour*60+l.minute,_hhmm(lon.get("start"),480),_hhmm(lon.get("end"),1020)) and bool(lon.get("enabled",True))
        nyx=_in_window(n.hour*60+n.minute,_hhmm(ny.get("start"),480),_hhmm(ny.get("end"),1020)) and bool(ny.get("enabled",True))
        if lo and nyx:
            z=cfg("LONDON_NY_OVERLAP",{}); return {"name":"LONDON_NY_OVERLAP","quality":float(z.get("weight",1.0)),"allow":bool(z.get("enabled",True))}
        if lo and a:
            z=cfg("ASIA_EUROPE_OVERLAP",{}); return {"name":"ASIA_EUROPE_OVERLAP","quality":float(z.get("weight",.86)),"allow":bool(z.get("enabled",True))}
        if lo: return {"name":"LONDON","quality":float(lon.get("weight",.88)),"allow":True}
        if nyx: return {"name":"NEW_YORK","quality":float(ny.get("weight",.92)),"allow":True}
        if a: return {"name":"ASIA","quality":float(asia.get("weight",.72)),"allow":True}
        return {"name":"OFF_SESSION","quality":0.0,"allow":bool(SESSION_CFG.get("off_session_allowed",False))}
    except (TypeError,ValueError,OSError,OverflowError):
        return {"name":"OFF_SESSION","quality":0.0,"allow":False}

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
    deltas = []
    for j in range(max(0, len(df)-8), len(df)):
        vv = float(df["volume"].iloc[j] or 0)
        tbv = float(df["taker_buy_volume"].iloc[j] or 0)
        deltas.append(2.0*(tbv/vv)-1.0 if vv>0 else 0.0)
    cvd = float(sum(deltas))
    strength = min(1.0, abs(delta) * 2.5 + min(0.30, abs(cvd)*0.08) + (0.25 if absorption else 0.0) + (0.15 if body > 0.55 else 0.0))
    return {"bias": bias, "strength": strength, "delta": delta, "cvd": cvd, "absorption": absorption}


def hyper_liquidity_proxy(df):
    """0-100 liquidity/participation proxy from OHLCV+taker flow.
    It is NOT an order-book depth measurement; no depth is fabricated."""
    if df is None or len(df)<25:
        return {"score":50.0,"quality":"UNKNOWN"}
    v=df["volume"].astype(float); rng=(df["high"]-df["low"]).astype(float)
    vm=float(v.iloc[-21:-1].mean()); vs=float(v.iloc[-21:-1].std() or 0.0)
    vz=(float(v.iloc[-1])-vm)/(vs if vs>0 else max(vm*0.1,1e-12))
    am=float(rng.iloc[-21:-1].mean()); rr=float(rng.iloc[-1])/(am if am>0 else 1e-12)
    score=max(0.0,min(100.0,50.0+12.0*vz+18.0*(rr-1.0)))
    q="HIGH" if score>=75 else "GOOD" if score>=60 else "LOW" if score<35 else "MEDIUM"
    return {"score":score,"quality":q}


def external_context(symbol):
    whale = _lookup(_json_env("WHALE_BIAS_JSON") or _load_json_file("WHALE_BIAS_FILE"), symbol)
    fundamental = _lookup(_json_env("FUNDAMENTAL_JSON") or _load_json_file("FUNDAMENTAL_FILE"), symbol)
    wbias = str(whale.get("bias", "NEUTRAL")).upper()
    wconf = max(0.0, min(1.0, float(whale.get("confidence", 0) or 0)))
    try:
        fscore = max(-5.0, min(5.0, float(fundamental.get("score", 0) or 0)))
    except (TypeError, ValueError):
        fscore = 0.0
    news_blocked = False
    news_age_minutes = None
    if not fundamental and os.getenv("NEWS_ENABLED", "1").strip().lower() not in {"0", "false", "no", "off"}:
        block_minutes = int(os.getenv("NEWS_BLOCK_MINUTES", "30") or 30)
        fscore, news_blocked, news_age_minutes = news_context(symbol, block_minutes=block_minutes)
    return {"whale_bias": wbias if wbias in {"BUY", "SELL", "NEUTRAL"} else "NEUTRAL", "whale_confidence": wconf, "fundamental_score": fscore, "news_blocked": news_blocked, "news_age_minutes": news_age_minutes}


def evaluate(symbol, direction, df_1h, *, min_session_quality=0.55, asset_class="CRYPTO"):

    fp = footprint_proxy(df_1h)
    sess = session_context(df_1h)
    hli = hyper_liquidity_proxy(df_1h)
    vp = vp_context(df_1h, len(df_1h)-1, lookback=min(60, max(20, len(df_1h)-1)), bins=40) if df_1h is not None and len(df_1h)>=25 else {"ok": False}
    ext = external_context(symbol)
    mode = os.getenv("SMART_CONTEXT_MODE", "live").strip().lower()
    # V30.6: all five configured sessions are eligible, but each has its own
    # minimum quality. Outside-session entries remain blocked.
    session_min = {
        "LONDON_NY_OVERLAP": 0.90,
        "ASIA_EUROPE_OVERLAP": 0.82,
        "LONDON": 0.84,
        "NEW_YORK": 0.92,
        "ASIA": 0.72,
    }.get(sess["name"], 999.0)
    # TradFi is 24/7 on WEEX but liquidity follows the underlying market.
    # Keep 24/7 availability while making thin/off-peak sessions materially
    # harder to trade; regular US hours are preferred for stocks/ETFs.
    if asset_class in {"STOCK", "ETF", "INDEX"}:
        session_min = {
            "LONDON_NY_OVERLAP": 0.98, "NEW_YORK": 0.92,
            "LONDON": 0.88, "ASIA_EUROPE_OVERLAP": 0.86, "ASIA": 0.99,
        }.get(sess["name"], 999.0)
    elif asset_class in {"METAL", "ENERGY", "FOREX"}:
        session_min = {
            "LONDON_NY_OVERLAP": 0.98, "LONDON": 0.88, "NEW_YORK": 0.92,
            "ASIA_EUROPE_OVERLAP": 0.86, "ASIA": 0.96,
        }.get(sess["name"], 999.0)
    if not sess["allow"]:
        return False, {"reason": "Outside configured sessions", "footprint": fp, "session": sess, "hyper_liquidity": hli, **ext}
    # External context is optional. It can only veto when supplied with real data.
    min_hli = float(os.getenv("MIN_HYPER_LIQUIDITY", "35") or 35)
    if hli["score"] < min_hli:
        return False, {"reason": "Hyper-Liquidity too low", "footprint": fp, "volume_profile": vp, "session": sess, "hyper_liquidity": hli, **ext}
    vp_buy = bool(vp.get("ok") and (vp.get("near_val") or vp.get("below_value") or (vp.get("inside_value") and vp.get("below_poc"))))
    vp_sell = bool(vp.get("ok") and (vp.get("near_vah") or vp.get("above_value") or (vp.get("inside_value") and vp.get("above_poc"))))
    if fp["bias"] in {"BUY", "SELL"} and fp["strength"] >= 0.65 and fp["bias"] != direction:
        return False, {"reason": "Footprint/OrderFlow conflict", "footprint": fp, "session": sess, "hyper_liquidity": hli, **ext}
    if ext["whale_confidence"] >= 0.70 and ext["whale_bias"] in {"BUY", "SELL"} and ext["whale_bias"] != direction:
        return False, {"reason": "Whale bias conflict", "footprint": fp, "session": sess, "hyper_liquidity": hli, **ext}
    if ext.get("news_blocked"):
        return False, {"reason": "Recent high-impact news blackout", "footprint": fp, "session": sess, "hyper_liquidity": hli, **ext}
    if (direction == "BUY" and ext["fundamental_score"] <= -3.0) or (direction == "SELL" and ext["fundamental_score"] >= 3.0):
        return False, {"reason": "Fundamental conflict", "footprint": fp, "session": sess, "hyper_liquidity": hli, **ext}
    if sess["quality"] < max(min_session_quality, session_min):
        return False, {"reason": "Low-liquidity session", "footprint": fp, "session": sess, "hyper_liquidity": hli, **ext}
    if gate_enabled("strict_symbol", True) and symbol.upper() in STRICT_SYMBOLS:
        if hli["score"] < STRICT_MIN_HLI:
            return False, {"reason": "Strict symbol filter: HLI too low", "footprint": fp, "session": sess, "hyper_liquidity": hli, **ext}
        if fp["bias"] != direction or fp["strength"] < 0.35:
            return False, {"reason": "Strict symbol filter: order-flow alignment insufficient", "footprint": fp, "volume_profile": vp, "session": sess, "hyper_liquidity": hli, **ext}
        if vp.get("ok") and ((direction == "BUY" and not (vp.get("near_val") or vp.get("below_value"))) or (direction == "SELL" and not (vp.get("near_vah") or vp.get("above_value")))):
            return False, {"reason": "Strict symbol filter: Volume Profile location insufficient", "footprint": fp, "volume_profile": vp, "session": sess, "hyper_liquidity": hli, **ext}
        if direction == "BUY" and not (vp.get("near_val") or vp.get("below_value")):
            return False, {"reason": "Strict symbol filter: Volume Profile VAL context insufficient", "footprint": fp, "volume_profile": vp, "session": sess, "hyper_liquidity": hli, **ext}
        if direction == "SELL" and not (vp.get("near_vah") or vp.get("above_value")):
            return False, {"reason": "Strict symbol filter: Volume Profile VAH context insufficient", "footprint": fp, "volume_profile": vp, "session": sess, "hyper_liquidity": hli, **ext}

    if gate_enabled("negative_session", True) and sess["name"] in NEGATIVE_SESSIONS:
        if hli["score"] < NEGATIVE_SESSION_MIN_HLI:
            return False, {"reason": "Strict negative-session filter: HLI too low", "footprint": fp, "session": sess, "hyper_liquidity": hli, **ext}
        if fp["bias"] != direction or fp["strength"] < 0.35:
            return False, {"reason": "Strict negative-session filter: order-flow alignment insufficient", "footprint": fp, "session": sess, "hyper_liquidity": hli, **ext}
        if vp.get("ok") and ((direction == "BUY" and not (vp.get("near_val") or vp.get("below_value"))) or (direction == "SELL" and not (vp.get("near_vah") or vp.get("above_value")))):
            return False, {"reason": "Strict negative-session filter: Volume Profile location insufficient", "footprint": fp, "volume_profile": vp, "session": sess, "hyper_liquidity": hli, **ext}

    # In live mode, a supplied strong aligned context adds confidence; absent data stays neutral.
    bonus = 0
    if fp["bias"] == direction and fp["strength"] >= 0.35: bonus += 1
    if ext["whale_bias"] == direction and ext["whale_confidence"] >= 0.50: bonus += 1
    if (direction == "BUY" and ext["fundamental_score"] > 1) or (direction == "SELL" and ext["fundamental_score"] < -1): bonus += 1
    if vp_buy and direction == "BUY": bonus += 1
    if vp_sell and direction == "SELL": bonus += 1
    return True, {"reason": "OK", "footprint": fp, "volume_profile": vp, "session": sess, "hyper_liquidity": hli, "bonus": bonus, "mode": mode, **ext}
