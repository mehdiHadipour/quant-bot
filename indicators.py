import math
import os
import pandas as pd
import ta

from logger import log

from config import (MIN_SIGNAL_PROBABILITY, MIN_ADX, STRICT_SYMBOLS, STRICT_MIN_SCORE,
                    NEGATIVE_SESSIONS, NEGATIVE_SESSION_MIN_SCORE, FIB_LOOKBACK, FIB_OTE_LOW, FIB_OTE_HIGH,
                    manual_tool, gate_enabled)
from smart_context import evaluate as evaluate_smart_context, session_context, hyper_liquidity_proxy
from regime_engine import classify as classify_regime
from ichimoku import ichimoku
from asset_universe import classify_symbol

# ema_200 needs a reasonable amount of history to be meaningful; below this
# the signal would be based on noise. fetch_klines requests 300 candles by
# default, so this should be comfortably satisfied in normal operation.
MIN_CANDLES = 210

# How many recent candles to look back over when checking for RSI divergence.
DIVERGENCE_LOOKBACK = 30


def detect_rsi_divergence(close_series, rsi_series, lookback=DIVERGENCE_LOOKBACK):
    """Lightweight RSI divergence check (no external peak-finding library
    needed): compares the current price/RSI point against the most extreme
    prior point in the lookback window.

    - "bearish": price is at/above its recent swing high, but RSI is lower
      than it was at that swing high (momentum fading on a fresh high).
    - "bullish": price is at/below its recent swing low, but RSI is higher
      than it was at that swing low (momentum improving on a fresh low).
    - None: no divergence detected, or not enough data yet.

    This is informational only — used as a caution flag in alert messages,
    it never blocks or forces a signal on its own.
    """
    if len(close_series) < lookback + 1 or len(rsi_series) < lookback + 1:
        return None

    window_close = close_series.iloc[-lookback:]
    window_rsi = rsi_series.iloc[-lookback:]

    if window_rsi.isna().any():
        return None

    prior_close = window_close.iloc[:-1]
    prior_rsi = window_rsi.iloc[:-1]

    current_close = window_close.iloc[-1]
    current_rsi = window_rsi.iloc[-1]

    prior_high_idx = prior_close.idxmax()
    prior_low_idx = prior_close.idxmin()

    if current_close >= prior_close.loc[prior_high_idx] and current_rsi < prior_rsi.loc[prior_high_idx]:
        return "bearish"

    if current_close <= prior_close.loc[prior_low_idx] and current_rsi > prior_rsi.loc[prior_low_idx]:
        return "bullish"

    return None


def get_timeframe_bias(df, min_candles=MIN_CANDLES):
    """EMA50-vs-EMA200 bias check, reusable for any timeframe (4H, 1D, ...).
    Returns 'BULL', 'BEAR', or None if data is insufficient or NaN."""
    if len(df) < min_candles:
        return None
    ema_50 = ta.trend.EMAIndicator(df['close'], window=50).ema_indicator().iloc[-1]
    ema_200 = ta.trend.EMAIndicator(df['close'], window=200).ema_indicator().iloc[-1]
    if pd.isna(ema_50) or pd.isna(ema_200):
        return None
    return "BULL" if ema_50 > ema_200 else "BEAR"


def analyze_market(df_15m, df_1h, df_4h, df_1d, symbol, funding_rate=None, reasons=None):
    """`reasons`, if passed a list, gets a human-readable explanation
    appended every time this returns None — so the caller can log WHY a
    symbol produced no signal this cycle instead of just silence. Optional
    and purely additive: return value/shape for existing callers/tests is
    unchanged (None on no-signal, dict on signal)."""
    def _skip(msg):
        if reasons is not None:
            reasons.append(msg)
        return None

    if len(df_1h) < MIN_CANDLES or len(df_4h) < MIN_CANDLES:
        return _skip(
            f"دادهٔ کافی نیست (1H: {len(df_1h)}، 4H: {len(df_4h)} کندل؛ حداقل لازم: {MIN_CANDLES})"
        )

    df = df_1h.copy()

    # --- Trend on 4H ---
    ema_50_4h = ta.trend.EMAIndicator(df_4h['close'], window=50).ema_indicator().iloc[-1]
    ema_200_4h = ta.trend.EMAIndicator(df_4h['close'], window=200).ema_indicator().iloc[-1]

    # --- Ichimoku context (9/26/52), used as a bounded confirmation vote.
    # The 4H and 1D clouds are computed only from completed bars and never
    # become a standalone entry trigger.
    ichi4 = ichimoku(df_4h, 9, 26, 52)
    ichi1 = ichimoku(df_1d, 9, 26, 52)
    ichi4_bull = bool(ichi4.bull.iloc[-1]) if not pd.isna(ichi4.bull.iloc[-1]) else False
    ichi4_bear = bool(ichi4.bear.iloc[-1]) if not pd.isna(ichi4.bear.iloc[-1]) else False
    ichi1_bull = bool(ichi1.bull.iloc[-1]) if not pd.isna(ichi1.bull.iloc[-1]) else False
    ichi1_bear = bool(ichi1.bear.iloc[-1]) if not pd.isna(ichi1.bear.iloc[-1]) else False

    # --- 1H core indicators ---
    current_open = df['open'].iloc[-1]
    current_high = df['high'].iloc[-1]
    current_low = df['low'].iloc[-1]
    current_close = df['close'].iloc[-1]
    current_volume = df['volume'].iloc[-1]
    current_taker_buy_volume = df['taker_buy_volume'].iloc[-1]
    atr = ta.volatility.AverageTrueRange(high=df['high'], low=df['low'], close=df['close'], window=14).average_true_range().iloc[-1]
    volume_ma = df['volume'].rolling(20).mean().iloc[-1]
    rsi_series = ta.momentum.RSIIndicator(df['close'], window=14).rsi()
    rsi = rsi_series.iloc[-1]
    macd_indicator = ta.trend.MACD(df['close'])
    macd = macd_indicator.macd().iloc[-1]
    macd_signal = macd_indicator.macd_signal().iloc[-1]
    ema_50 = ta.trend.EMAIndicator(df['close'], window=50).ema_indicator().iloc[-1]
    ema_200 = ta.trend.EMAIndicator(df['close'], window=200).ema_indicator().iloc[-1]

    # --- New: trend-strength (ADX), volatility bands (Bollinger), extra
    # momentum confirmation (Stochastic) ---
    adx = ta.trend.ADXIndicator(high=df['high'], low=df['low'], close=df['close'], window=14).adx().iloc[-1]

    bb = ta.volatility.BollingerBands(close=df['close'], window=20, window_dev=2)
    bb_pband = bb.bollinger_pband().iloc[-1]  # position within bands: <0 below lower, >1 above upper

    stoch_indicator = ta.momentum.StochasticOscillator(high=df['high'], low=df['low'], close=df['close'], window=14, smooth_window=3)
    stoch = stoch_indicator.stoch().iloc[-1]
    stoch_signal = stoch_indicator.stoch_signal().iloc[-1]

    # --- VWAP (Volume Weighted Average Price), rolling over the last 20
    # candles. A true "session VWAP" resets at a fixed daily boundary,
    # which needs candle open-times we don't currently track; a rolling
    # window is the standard practical substitute and still captures
    # "is price trading above/below where most recent volume changed
    # hands" — a genuine value-area reference, not a fabricated one.
    typical_price = (df['high'] + df['low'] + df['close']) / 3
    vwap_series = (typical_price * df['volume']).rolling(20).sum() / df['volume'].rolling(20).sum()
    vwap = vwap_series.iloc[-1]

    # --- Fair Value Gap (FVG): a 3-candle imbalance pattern. A bullish FVG
    # forms when candle[-3]'s high is below candle[-1]'s low (price moved
    # up so fast that no trading occurred in that range) — the mirror for
    # bearish. Purely from OHLC data already on hand.
    fvg = None
    if len(df) >= 3:
        high_2ago = df['high'].iloc[-3]
        low_2ago = df['low'].iloc[-3]
        if current_low > high_2ago:
            fvg = "bullish"
        elif current_high < low_2ago:
            fvg = "bearish"

    # If any indicator came back NaN (can happen with gappy/incomplete
    # candle data from the exchange), bail out instead of risking a
    # comparison against NaN, which silently evaluates to False and could
    # produce a misleading signal rather than an obvious error.
    critical_values = [
        ema_50_4h, ema_200_4h, current_open, current_high, current_low, current_close,
        current_volume, current_taker_buy_volume, atr, volume_ma, rsi, macd, macd_signal,
        ema_50, ema_200, adx, bb_pband, stoch, stoch_signal, vwap,
    ]
    if any(pd.isna(v) for v in critical_values):
        log.warning(f"{symbol}: insufficient/incomplete indicator data this cycle, skipping.")
        return _skip("داده‌های اندیکاتور ناقص بود (NaN) — احتمالاً کندل‌های ناقص از صرافی")

    if current_close <= 0:
        return _skip("قیمت نامعتبر دریافت شد")

    # --- Hard filter: skip ranging / weak-trend markets ---
    # ADX below the configured threshold means there is no meaningful trend
    # to trade with (classic "choppy market" condition), regardless of how
    # the other scores look.
    if gate_enabled("adx", True) and adx < MIN_ADX:
        return _skip(f"ADX {adx:.1f} < حداقل {MIN_ADX} → بازار رنج/بدون روند کافی است")

    divergence = detect_rsi_divergence(df['close'], rsi_series)

    market_bias = "BULL" if ema_50_4h > ema_200_4h else "BEAR"

    atr_percent = (atr / current_close) * 100
    if gate_enabled("low_atr", True) and atr_percent < 0.5:
        return _skip(f"نوسان خیلی کم است (ATR {atr_percent:.2f}٪ < حداقل 0.5٪)")

    # Volume and break-of-structure
    volume_ratio = df['volume'].iloc[-1] / volume_ma if volume_ma > 0 else 0
    prev_high = df['high'].iloc[-21:-1].max()
    prev_low = df['low'].iloc[-21:-1].min()

    structure_score = 0
    breakout_up = current_close > prev_high and volume_ratio > 1.8
    breakout_down = current_close < prev_low and volume_ratio > 1.8
    if breakout_up:
        structure_score = 25
    elif breakout_down:
        structure_score = -25

    # --- ICT-style Liquidity Sweep: a wick that pierces beyond a recent
    # swing high/low (the same 20-candle prev_high/prev_low used for the
    # breakout check above — exactly where stop-loss orders commonly
    # cluster) and then CLOSES back inside that range is the classic sign
    # of a stop-hunt/liquidity grab immediately followed by a reversal —
    # the opposite read of a genuine breakout. This is mutually exclusive
    # with breakout_up/breakout_down by construction (breakout needs the
    # CLOSE beyond the level; a sweep needs the close back INSIDE it), so
    # it can never double-count with structure_score for the same candle.
    liquidity_sweep = None
    sweep_score = 0
    swept_sell_side = current_low < prev_low
    swept_buy_side = current_high > prev_high
    if swept_sell_side and current_close > prev_low:
        liquidity_sweep = "bullish"
        sweep_score = 12
    elif swept_buy_side and current_close < prev_high:
        liquidity_sweep = "bearish"
        sweep_score = -12

    # Bollinger confirmation: a breakout that is also pushing outside the
    # bands is much more likely to be a genuine move than a fake-out inside
    # a range, so it only adds score when it agrees with the breakout.
    bb_score = 0
    if breakout_up and bb_pband > 1:
        bb_score = 10
    elif breakout_down and bb_pband < 0:
        bb_score = -10

    # Stochastic momentum confirmation (independent of RSI/MACD)
    stoch_score = 0
    if stoch > stoch_signal and stoch < 80:
        stoch_score = 10
    elif stoch < stoch_signal and stoch > 20:
        stoch_score = -10

    # --- Candle wick/shadow rejection: a long lower wick relative to the
    # candle's body means price was pushed down and then rejected back up
    # within the same candle (buyers stepped in at the low) — classic
    # price-action rejection, independent of the close-based indicators
    # above. A long upper wick is the bearish mirror.
    body = abs(current_close - current_open)
    upper_wick = current_high - max(current_open, current_close)
    lower_wick = min(current_open, current_close) - current_low
    wick_score = 0
    if lower_wick > 2 * max(body, 1e-9) and lower_wick > upper_wick:
        wick_score = 10
    elif upper_wick > 2 * max(body, 1e-9) and upper_wick > lower_wick:
        wick_score = -10

    # --- Order-flow proxy: Binance's kline data includes how much of a
    # candle's volume came from aggressive taker BUY orders (hitting the
    # ask) vs. the rest (taker sells hitting the bid). A candle where most
    # volume was taker-buy-initiated reflects genuine buying pressure, and
    # vice versa — a real, free proxy for order flow without needing
    # tick-level trade data.
    buy_ratio = current_taker_buy_volume / current_volume if current_volume > 0 else 0.5
    order_flow_score = 0
    if buy_ratio > 0.55:
        order_flow_score = 10
    elif buy_ratio < 0.45:
        order_flow_score = -10

    # --- VWAP position: trading meaningfully above/below the rolling
    # value-area reference is standalone directional evidence, similar to
    # a moving-average cross.
    vwap_score = 0
    if current_close > vwap * 1.001:
        vwap_score = 10
    elif current_close < vwap * 0.999:
        vwap_score = -10

    # --- Fair Value Gap confirmation: a freshly-formed imbalance in the
    # direction of the move adds conviction (the market moved fast enough
    # to leave a gap, evidence of aggressive participation).
    fvg_score = 0
    if fvg == "bullish":
        fvg_score = 10
    elif fvg == "bearish":
        fvg_score = -10

    # Ichimoku confirmation: reward alignment with the 4H/1D trend without
    # forcing a trade when the cloud is neutral. This avoids over-filtering.
    ichimoku_score = 0
    if market_bias == "BULL" and (ichi4_bull or ichi1_bull):
        ichimoku_score = 8
    elif market_bias == "BEAR" and (ichi4_bear or ichi1_bear):
        ichimoku_score = -8

    # --- Fibonacci retracement context (50-bar completed dealing range).
    # This is a confirmation/location vote, never a standalone trigger.
    # 50%-78.6% is treated as the preferred pullback zone; 61.8%-78.6%
    # is additionally marked as OTE. Only completed bars are used.
    fib_hi = df['high'].shift(1).rolling(FIB_LOOKBACK, min_periods=FIB_LOOKBACK).max().iloc[-1]
    fib_lo = df['low'].shift(1).rolling(FIB_LOOKBACK, min_periods=FIB_LOOKBACK).min().iloc[-1]
    fib_range = fib_hi - fib_lo if pd.notna(fib_hi) and pd.notna(fib_lo) else float('nan')
    fib_score = 0
    fib_zone = 'NONE'
    fib_ote = False
    if pd.notna(fib_range) and fib_range > 0:
        if market_bias == 'BULL':
            f50 = fib_hi - 0.50 * fib_range
            f618 = fib_hi - FIB_OTE_LOW * fib_range
            f786 = fib_hi - FIB_OTE_HIGH * fib_range
            fib_ote = f786 <= current_close <= f618
            fib_mid = f50 <= current_close < f618
        else:
            f50 = fib_lo + 0.50 * fib_range
            f618 = fib_lo + FIB_OTE_LOW * fib_range
            f786 = fib_lo + FIB_OTE_HIGH * fib_range
            fib_ote = f618 <= current_close <= f786
            fib_mid = f618 < current_close <= f50
        if fib_ote:
            fib_score = 10 if market_bias == 'BULL' else -10
            fib_zone = 'OTE'
        elif fib_mid:
            fib_score = 4 if market_bias == 'BULL' else -4
            fib_zone = 'MID'

    # --- Funding rate (perpetual futures, free/public): a strongly
    # positive rate means longs are paying shorts a lot to stay open —
    # the market is crowded/over-leveraged long, which historically tends
    # to precede long squeezes/pullbacks. The mirror is true for a
    # strongly negative rate. This is intentionally a *contrarian*, modest
    # weight (not a primary directional signal) and is fully skipped
    # (score 0) when the funding endpoint couldn't be reached, so a
    # failed fetch never blocks or biases a signal.
    FUNDING_EXTREME = 0.0005  # 0.05% per 8h — a commonly-cited "hot" level
    funding_score = 0
    if funding_rate is not None:
        if funding_rate > FUNDING_EXTREME:
            funding_score = -8
        elif funding_rate < -FUNDING_EXTREME:
            funding_score = 8

    # V30.9.7 regime classification: configurable and shared with live/backtest.
    regime = classify_regime(df_1h)

    # --- Scoring (weights sum to a comparable magnitude in both directions,
    # which matters for the sigmoid below to be fair to BUY and SELL alike)
    trend_score = 20 if ema_50 > ema_200 else -20

    # Symmetric momentum: MACD cross direction gated by a "healthy trend"
    # RSI band (30-70) on both sides, instead of the earlier asymmetric
    # version that only ever penalized bearish momentum in the RSI>70 edge
    # case and never rewarded a clean bearish MACD cross the way it did
    # for bullish crosses.
    if macd > macd_signal and 30 < rsi < 70:
        momentum_score = 15
    elif macd < macd_signal and 30 < rsi < 70:
        momentum_score = -15
    else:
        momentum_score = 0

    # Volume and ATR-quality are confirmation signals about how much to
    # trust whichever direction the trend/structure are already pointing —
    # not standalone bullish signals. Earlier versions always added them as
    # a flat positive number regardless of direction, which quietly dragged
    # every bearish (SELL) total_score back toward zero while reinforcing
    # every bullish (BUY) one. Scaling by the preliminary directional lean
    # (from trend + structure, the two strongest directional signals)
    # fixes that bias.
    direction_lean = 1 if (trend_score + structure_score) >= 0 else -1
    volume_score = (10 if volume_ratio > 1.5 else 0) * direction_lean
    risk_score = (15 if atr_percent < 2.0 else 5) * direction_lean

    # V30.9.2 manual weighted scoring. Each tool contributes at most its
    # configured weight, preserving BUY/SELL symmetry. Disabled tools contribute 0.
    def _w(name, raw):
        cfg = manual_tool(name)
        if cfg and not bool(cfg.get("enabled", True)):
            return 0.0
        weight = float(cfg.get("weight", abs(raw))) if cfg else float(abs(raw))
        return weight if raw > 0 else -weight if raw < 0 else 0.0

    total_score = sum((
        _w("trend", trend_score),
        _w("macd", momentum_score),
        _w("stochastic", stoch_score),
        _w("volume", volume_score),
        _w("structure", structure_score),
        _w("bollinger", bb_score),
        _w("risk_quality", risk_score),
        _w("wick", wick_score),
        _w("order_flow", order_flow_score),
        _w("vwap", vwap_score),
        _w("fvg", fvg_score),
        _w("funding", funding_score),
        _w("liquidity_sweep", sweep_score),
        _w("ichimoku", ichimoku_score),
        _w("fibonacci", fib_score),
    ))

    # V30.6 session weighting: active sessions are not treated equally.
    sess_ctx = session_context(df_1h)
    from config import REGIME_CFG, SESSION_CFG
    session_bonus = float((SESSION_CFG.get(sess_ctx.get("name"), {}) or {}).get("score_bonus", 0.0))
    if REGIME_CFG.get("enabled", True) and regime.get("name") == "UNKNOWN" and not REGIME_CFG.get("allow_unknown", False):
        return _skip("Regime UNKNOWN: معامله مجاز نیست")
    if REGIME_CFG.get("enabled", True) and regime.get("confidence",0) < float(REGIME_CFG.get("min_confidence",65)):
        return _skip(f"Regime confidence پایین است: {regime.get('confidence',0):.1f}%")
    if sess_ctx.get("name") == "OFF_SESSION" and not sess_ctx.get("allow",False):
        return _skip("OFF_SESSION: معامله طبق تنظیمات مجاز نیست")
    total_score += session_bonus if total_score >= 0 else -session_bonus

    # Probabilities. IMPORTANT: both branches must use the SAME sign in the
    # exponent (-abs(total_score)/20) so that a stronger signal in either
    # direction produces a HIGHER probability. An earlier version of this
    # formula used +abs(total_score)/20 for sell_prob, which made stronger
    # bearish setups score a *lower* sell probability — the opposite of
    # what was intended, and the root cause of SELL signals almost never
    # clearing the confidence threshold regardless of how strong the
    # downtrend actually was. Confirmed and fixed after a real report of
    # the bot missing an obvious short opportunity.
    buy_prob = 100 / (1 + math.exp(-abs(total_score) / 20)) if total_score > 0 else 0
    sell_prob = 100 / (1 + math.exp(-abs(total_score) / 20)) if total_score < 0 else 0
    neutral_prob = 100 - buy_prob - sell_prob

    # Weak-signal filter: only act on signals whose probability clears the
    # configured confidence bar (default 60%), on top of the market-bias
    # agreement check that was already required.
    direction = None
    if total_score > 0 and buy_prob >= MIN_SIGNAL_PROBABILITY:
        direction = "BUY"
    elif total_score < 0 and sell_prob >= MIN_SIGNAL_PROBABILITY:
        direction = "SELL"

    # Session-specific confidence threshold. NY is deliberately stricter
    # because it was the weakest session in the prior sample; Asia is also
    # selective, while the two overlaps receive the best treatment.
    session_threshold = float((SESSION_CFG.get(sess_ctx.get("name"), {}) or {}).get("min_score", 999.0))
    if direction == "BUY" and buy_prob < session_threshold:
        direction = None
    if direction == "SELL" and sell_prob < session_threshold:
        direction = None

    # Optional manual hard gates for individual tools. These are evaluated only
    # after direction is known, and therefore cannot create a direction by themselves.
    for _tool_name, _ok in (("liquidity_sweep", ((direction == "BUY" and liquidity_sweep == "bullish") or (direction == "SELL" and liquidity_sweep == "bearish"))),
                            ("fvg", ((direction == "BUY" and fvg == "bullish") or (direction == "SELL" and fvg == "bearish")))):
        _tcfg = manual_tool(_tool_name)
        if _tcfg.get("enabled", True) and str(_tcfg.get("mode", "score")).lower() == "hard" and direction is not None and not _ok:
            return _skip(f"Manual hard gate: {_tool_name} failed")

    # Hard Fibonacci gate: by user policy, NO signal is allowed unless the
    # current closed bar is inside the directional 61.8%-78.6% OTE zone.
    # This is evaluated from prior completed bars only, so it is leakage-safe.
    if gate_enabled("fib_ote", True) and direction is not None and os.getenv("REQUIRE_FIB_OTE", "1").strip().lower() not in {"0", "false", "no", "off"} and not fib_ote:
        return _skip(f"سیگنال {direction} خارج از Fibonacci OTE است؛ ورود ممنوع")

    if direction is None:
        return _skip(
            f"سیگنال به آستانهٔ اطمینان نرسید (بایاس 4H: {market_bias}، "
            f"احتمال BUY: {buy_prob:.1f}٪، احتمال SELL: {sell_prob:.1f}٪، "
            f"حداقل لازم: {MIN_SIGNAL_PROBABILITY:.0f}٪) — total_score={total_score:.1f}"
        )

    # --- Multi-timeframe confluence (quality over quantity) ---
    # 1D trend must agree with the 4H trend bias that produced this signal;
    # if the daily chart disagrees, this is a lower-conviction counter-trend
    # setup on the bigger picture and is skipped rather than traded.
    daily_bias = get_timeframe_bias(df_1d)
    if daily_bias is None:
        return _skip("بایاس 1D برای تأیید کافی نیست")
    if gate_enabled("htf_alignment", True) and daily_bias != market_bias:
        # Counter-trend is allowed only with materially stronger confluence.
        # This prevents the old one-way gate from suppressing every BUY while
        # still refusing ordinary counter-trend noise.
        macd_align = (direction == "BUY" and macd > macd_signal) or (direction == "SELL" and macd < macd_signal)
        if gate_enabled("countertrend", True) and (abs(total_score) < 78 or not fib_ote or not macd_align):
            return _skip(
                f"سیگنال {direction} خلاف بایاس روزانه بود و شرایط Counter-Trend کافی نبود "
                f"(score={total_score:.1f}, Fib OTE={fib_ote}, MACD={macd_align})"
            )

    # 15m short-term confirmation: don't enter if the very short-term
    # momentum is already pointing the other way (e.g. a BUY signal right
    # as the 15m chart is rolling over). Kept intentionally simple — a
    # single EMA20 check, not a full second scoring system.
    if gate_enabled("short_term_ema", True) and len(df_15m) >= 20:
        ema_20_15m = ta.trend.EMAIndicator(df_15m['close'], window=20).ema_indicator().iloc[-1]
        current_15m_close = df_15m['close'].iloc[-1]
        if not pd.isna(ema_20_15m):
            if direction == "BUY" and current_15m_close < ema_20_15m:
                return _skip(
                    f"سیگنال BUY روی 4H/1D تأیید شد اما مومنتوم کوتاه‌مدت 15m هنوز برنگشته "
                    f"(قیمت {current_15m_close:,.2f} زیر EMA20 پانزده‌دقیقه‌ای {ema_20_15m:,.2f})"
                )
            if direction == "SELL" and current_15m_close > ema_20_15m:
                return _skip(
                    f"سیگنال SELL روی 4H/1D تأیید شد اما مومنتوم کوتاه‌مدت 15m هنوز برنگشته "
                    f"(قیمت {current_15m_close:,.2f} بالای EMA20 پانزده‌دقیقه‌ای {ema_20_15m:,.2f})"
                )

    # Final Smart Context gate: order-flow/footprint proxy, global session,
    # and optional whale/fundamental sidecars. Missing external data is neutral.
    smart_ok, smart = evaluate_smart_context(symbol, direction, df_1h, asset_class=classify_symbol(symbol))
    if gate_enabled("smart_context", True) and not smart_ok:
        return _skip(f"Smart Context: {smart.get('reason', 'رد شد')}")

    if gate_enabled("strict_symbol", True) and symbol.upper() in STRICT_SYMBOLS:
        hli_now = float(smart.get("hyper_liquidity", {}).get("score", 0) or 0)
        macd_align = (direction == "BUY" and macd > macd_signal) or (direction == "SELL" and macd < macd_signal)
        if hli_now < float(os.getenv("STRICT_MIN_HLI", str(70.0))) or not fib_ote:
            return _skip(f"Strict symbol filter: HLI/Fibonacci OTE کافی نیست (HLI={hli_now:.1f}, OTE={fib_ote})")
        if not macd_align:
            return _skip("Strict symbol filter: MACD هم‌جهت نیست")
        if abs(total_score) < STRICT_MIN_SCORE:
            return _skip(f"Strict symbol filter: confluence score کافی نیست (score={abs(total_score):.1f})")

    if gate_enabled("negative_session", True) and smart.get("session", {}).get("name") in NEGATIVE_SESSIONS:
        hli_now = float(smart.get("hyper_liquidity", {}).get("score", 0) or 0)
        macd_align = (direction == "BUY" and macd > macd_signal) or (direction == "SELL" and macd < macd_signal)
        if hli_now < float(os.getenv("NEGATIVE_SESSION_MIN_HLI", "70")) or not fib_ote or not macd_align:
            return _skip("Strict negative-session filter: OTE + MACD + HLI لازم است")
        if abs(total_score) < NEGATIVE_SESSION_MIN_SCORE:
            return _skip(f"Strict negative-session filter: confluence score کافی نیست (score={abs(total_score):.1f})")

    smart_bonus = int(smart.get("bonus", 0) or 0)
    if smart_bonus:
        if direction == "BUY":
            buy_prob = min(99.0, buy_prob + 2.0 * smart_bonus)
        else:
            sell_prob = min(99.0, sell_prob + 2.0 * smart_bonus)
        neutral_prob = max(0.0, 100.0 - buy_prob - sell_prob)

    return {"direction": direction, "buy": buy_prob, "sell": sell_prob, "neutral": neutral_prob, "atr": atr, "price": current_close, "symbol": symbol, "adx": adx, "divergence": divergence, "buy_ratio": buy_ratio, "fvg": fvg, "vwap": vwap, "funding_rate": funding_rate, "liquidity_sweep": liquidity_sweep, "ichimoku": {"4h_bull": ichi4_bull, "4h_bear": ichi4_bear, "1d_bull": ichi1_bull, "1d_bear": ichi1_bear, "score": ichimoku_score}, "fibonacci": {"enabled": True, "required_ote": os.getenv("REQUIRE_FIB_OTE", "1").strip().lower() not in {"0", "false", "no", "off"}, "lookback": FIB_LOOKBACK, "zone": fib_zone, "ote": fib_ote, "score": fib_score, "swing_high": float(fib_hi) if pd.notna(fib_hi) else None, "swing_low": float(fib_lo) if pd.notna(fib_lo) else None, "f50": float(f50) if "f50" in locals() and pd.notna(f50) else None, "f618": float(f618) if "f618" in locals() and pd.notna(f618) else None, "f786": float(f786) if "f786" in locals() and pd.notna(f786) else None}, "diagnostics": {"liquidity_sweep": liquidity_sweep, "order_flow_bias": smart.get("footprint", {}).get("bias", "NEUTRAL"), "order_flow_strength": smart.get("footprint", {}).get("strength", 0.0), "volume_profile": smart.get("volume_profile", {}), "hyper_liquidity": smart.get("hyper_liquidity", {}), "session": smart.get("session", {}), "regime": regime, "macd_aligned": ((direction == "BUY" and macd > macd_signal) or (direction == "SELL" and macd < macd_signal)), "fibonacci_ote": fib_ote}, "smart_context": smart}
