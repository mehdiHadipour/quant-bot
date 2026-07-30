import math
import pandas as pd
import ta


from config import (
    MIN_SIGNAL_PROBABILITY,
    MIN_ADX,
    MIN_ATR_PERCENT,
    MAX_ATR_PERCENT,
    MIN_SIGNAL_SCORE,
)

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


def _safe_sigmoid_confidence(score, scale=45.0):
    """Map directional score magnitude to a human-readable confidence.

    This is a confidence score, not a statistically calibrated probability.
    The old implementation called a one-sided sigmoid a probability and
    assigned the opposite side exactly 0%, which made alerts look much more
    certain than the evidence justified.
    """
    return 50.0 + 50.0 * math.tanh(abs(float(score)) / scale)


def _directional_components(df, df_4h, funding_rate=None):
    """Compute directional evidence from completed candles only."""
    close = df["close"]
    high = df["high"]
    low = df["low"]
    volume = df["volume"]

    atr = ta.volatility.AverageTrueRange(high=high, low=low, close=close, window=14).average_true_range().iloc[-1]
    rsi_series = ta.momentum.RSIIndicator(close, window=14).rsi()
    rsi = rsi_series.iloc[-1]
    macd_indicator = ta.trend.MACD(close)
    macd = macd_indicator.macd().iloc[-1]
    macd_signal = macd_indicator.macd_signal().iloc[-1]
    ema_20 = ta.trend.EMAIndicator(close, window=20).ema_indicator().iloc[-1]
    ema_50 = ta.trend.EMAIndicator(close, window=50).ema_indicator().iloc[-1]
    ema_200 = ta.trend.EMAIndicator(close, window=200).ema_indicator().iloc[-1]

    adx_ind = ta.trend.ADXIndicator(high=high, low=low, close=close, window=14)
    adx = adx_ind.adx().iloc[-1]
    di_plus = adx_ind.adx_pos().iloc[-1]
    di_minus = adx_ind.adx_neg().iloc[-1]

    bb = ta.volatility.BollingerBands(close=close, window=20, window_dev=2)
    bb_pband = bb.bollinger_pband().iloc[-1]

    stoch_ind = ta.momentum.StochasticOscillator(
        high=high, low=low, close=close, window=14, smooth_window=3
    )
    stoch = stoch_ind.stoch().iloc[-1]
    stoch_signal = stoch_ind.stoch_signal().iloc[-1]

    volume_ma = volume.rolling(20).mean().iloc[-1]
    volume_ratio = volume.iloc[-1] / volume_ma if volume_ma > 0 else 0.0

    typical = (high + low + close) / 3
    vwap = (typical * volume).rolling(20).sum().iloc[-1] / volume.rolling(20).sum().iloc[-1]

    prev_high = high.iloc[-21:-1].max()
    prev_low = low.iloc[-21:-1].min()
    current_open, current_high, current_low, current_close = (
        df["open"].iloc[-1], high.iloc[-1], low.iloc[-1], close.iloc[-1]
    )

    breakout_up = current_close > prev_high and volume_ratio >= 1.5
    breakout_down = current_close < prev_low and volume_ratio >= 1.5

    # FVG is initialized on every path so the result payload is always defined.
    fvg = None
    if len(df) >= 3:
        if low.iloc[-1] > high.iloc[-3]:
            fvg = "bullish"
        elif high.iloc[-1] < low.iloc[-3]:
            fvg = "bearish"

    liquidity_sweep = None
    swept_sell_side = current_low < prev_low
    swept_buy_side = current_high > prev_high
    if swept_sell_side and current_close > prev_low:
        liquidity_sweep = "bullish"
    elif swept_buy_side and current_close < prev_high:
        liquidity_sweep = "bearish"

    body = abs(current_close - current_open)
    upper_wick = current_high - max(current_open, current_close)
    lower_wick = min(current_open, current_close) - current_low

    buy_ratio = (
        df["taker_buy_volume"].iloc[-1] / current_volume
        if (current_volume := float(df["volume"].iloc[-1])) > 0 else 0.5
    )

    # Directional scoring. Every contributor is signed; there are no
    # "positive risk/volume" points that accidentally weaken SELL signals.
    components = {}
    components["Trend (EMA)"] = 18 if ema_50 > ema_200 else -18
    # Use the same EMA50-vs-EMA200 regime definition on 4H that is used
    # everywhere else. The previous implementation compared 4H price only
    # with EMA200, which could label a recovering market BEAR for a long time
    # even after EMA50 had crossed above EMA200. That asymmetry was a major
    # source of persistent SELL bias in walk-forward results.
    bias_4h_score = get_timeframe_bias(df_4h)
    if bias_4h_score == "BULL":
        components["4H Trend"] = 16
    elif bias_4h_score == "BEAR":
        components["4H Trend"] = -16

    if macd > macd_signal:
        components["MACD"] = 10
    elif macd < macd_signal:
        components["MACD"] = -10

    if 45 <= rsi <= 68 and macd > macd_signal:
        components["RSI Momentum"] = 8
    elif 32 <= rsi <= 55 and macd < macd_signal:
        components["RSI Momentum"] = -8

    if di_plus > di_minus:
        components["DMI"] = min(14, max(0, (di_plus - di_minus) / 2))
    elif di_minus > di_plus:
        components["DMI"] = -min(14, max(0, (di_minus - di_plus) / 2))

    if current_close > ema_20:
        components["EMA20"] = 6
    elif current_close < ema_20:
        components["EMA20"] = -6

    if breakout_up:
        components["Breakout"] = 14
    elif breakout_down:
        components["Breakout"] = -14

    if liquidity_sweep == "bullish":
        components["Liquidity Sweep"] = 10
    elif liquidity_sweep == "bearish":
        components["Liquidity Sweep"] = -10

    if stoch > stoch_signal and stoch < 85:
        components["Stochastic"] = 6
    elif stoch < stoch_signal and stoch > 15:
        components["Stochastic"] = -6

    if current_close > vwap * 1.001:
        components["VWAP"] = 7
    elif current_close < vwap * 0.999:
        components["VWAP"] = -7

    if volume_ratio >= 1.5:
        components["Volume"] = 6 if current_close >= current_open else -6

    if buy_ratio > 0.55:
        components["Order Flow"] = 7
    elif buy_ratio < 0.45:
        components["Order Flow"] = -7

    if bb_pband > 1.0 and current_close > current_open:
        components["Bollinger"] = 5
    elif bb_pband < 0.0 and current_close < current_open:
        components["Bollinger"] = -5

    if lower_wick > 2 * max(body, 1e-9) and lower_wick > upper_wick:
        components["Wick Rejection"] = 5
    elif upper_wick > 2 * max(body, 1e-9) and upper_wick > lower_wick:
        components["Wick Rejection"] = -5

    if funding_rate is not None:
        if funding_rate > 0.0005:
            components["Funding"] = -5
        elif funding_rate < -0.0005:
            components["Funding"] = 5

    return {
        "components": {k: v for k, v in components.items() if abs(v) > 0.01},
        "atr": float(atr),
        "rsi": float(rsi),
        "adx": float(adx),
        "di_plus": float(di_plus),
        "di_minus": float(di_minus),
        "bb_pband": float(bb_pband),
        "stoch": float(stoch),
        "stoch_signal": float(stoch_signal),
        "vwap": float(vwap),
        "buy_ratio": float(buy_ratio),
        "volume_ratio": float(volume_ratio),
        "ema_20": float(ema_20),
        "ema_50": float(ema_50),
        "ema_200": float(ema_200),
        "liquidity_sweep": liquidity_sweep,
        "fvg": d["fvg"],
        "divergence": detect_rsi_divergence(close, rsi_series),
    }


def analyze_market(df_15m, df_1h, df_4h, df_1d, symbol, funding_rate=None, reasons=None):
    """Conservative multi-timeframe signal engine.

    Key safety rules:
    - only completed candles are accepted by the caller;
    - 4H and 1D regime must agree;
    - 15m must confirm direction and slope, not merely price vs EMA;
    - ATR must be finite and inside a tradable volatility band;
    - BUY/SELL confidence is derived from the same signed score;
    - the signal must have a minimum absolute score and directional edge.
    """
    def _skip(msg):
        if reasons is not None:
            reasons.append(msg)
        return None

    if any(x is None or len(x) < MIN_CANDLES for x in (df_1h, df_4h)):
        return _skip("دادهٔ کافی برای EMA200 در 1H/4H وجود ندارد.")

    if df_15m is None or df_15m.empty:
        return _skip("دادهٔ 15m برای تأیید ورود در دسترس نیست.")
    if df_1d is None or len(df_1d) < MIN_CANDLES:
        return _skip("دادهٔ کافی برای رژیم 1D وجود ندارد.")

    if any(c not in df_1h.columns for c in ("open", "high", "low", "close", "volume", "taker_buy_volume")):
        return _skip("ستون‌های OHLCV/تیکر-بای ناقص هستند.")

    d = _directional_components(df_1h, df_4h, funding_rate)
    critical = [
        d["atr"], d["rsi"], d["adx"], d["di_plus"], d["di_minus"],
        d["bb_pband"], d["stoch"], d["stoch_signal"], d["vwap"],
        d["volume_ratio"], d["buy_ratio"],
    ]
    if any(pd.isna(v) or not math.isfinite(float(v)) for v in critical):
        return _skip("یکی از اندیکاتورهای اصلی NaN/غیرعددی است.")

    price = float(df_1h["close"].iloc[-1])
    atr_percent = d["atr"] / price * 100
    if price <= 0 or d["atr"] <= 0:
        return _skip("قیمت یا ATR نامعتبر/صفر است.")
    if not MIN_ATR_PERCENT <= atr_percent <= MAX_ATR_PERCENT:
        return _skip(
            f"نوسان نامناسب است: ATR={atr_percent:.2f}%؛ بازه مجاز "
            f"{MIN_ATR_PERCENT:.2f}% تا {MAX_ATR_PERCENT:.2f}%."
        )
    if d["adx"] < MIN_ADX:
        return _skip(f"ADX {d['adx']:.1f} < {MIN_ADX:.1f}; بازار روند کافی ندارد.")

    bias_4h = get_timeframe_bias(df_4h)
    bias_1d = get_timeframe_bias(df_1d)
    if bias_4h is None or bias_1d is None or bias_4h != bias_1d:
        return _skip(f"رژیم 4H/1D هم‌جهت نیست: 4H={bias_4h}, 1D={bias_1d}.")

    score = float(sum(d["components"].values()))
    direction = "BUY" if score > 0 else "SELL"
    confidence = _safe_sigmoid_confidence(score)

    # A single weak signal is never enough. The directional edge is checked
    # against the opposite side's score, which prevents tiny sign changes
    # around zero from flipping BUY to SELL between cycles.
    if abs(score) < MIN_SIGNAL_SCORE:
        return _skip(f"امتیاز جهت‌دار {score:+.1f} کمتر از حداقل {MIN_SIGNAL_SCORE:.1f} است.")
    if confidence < MIN_SIGNAL_PROBABILITY:
        return _skip(
            f"اعتماد {confidence:.1f}% کمتر از حداقل {MIN_SIGNAL_PROBABILITY:.1f}% است."
        )

    regime_direction = "BUY" if bias_4h == "BULL" else "SELL"
    if direction != regime_direction:
        return _skip(
            f"جهت کوتاه‌مدت {direction} خلاف رژیم 4H/1D ({regime_direction}) است."
        )

    # 15m confirmation: EMA20 slope + close position + MACD direction.
    ema20_15 = ta.trend.EMAIndicator(df_15m["close"], window=20).ema_indicator()
    macd15 = ta.trend.MACD(df_15m["close"])
    if len(df_15m) < 30 or pd.isna(ema20_15.iloc[-1]) or pd.isna(ema20_15.iloc[-2]):
        return _skip("دادهٔ 15m برای تأیید مومنتوم کافی نیست.")
    slope_up = ema20_15.iloc[-1] > ema20_15.iloc[-2]
    close15 = float(df_15m["close"].iloc[-1])
    ema15 = float(ema20_15.iloc[-1])
    macd15_now = macd15.macd().iloc[-1]
    macd15_sig = macd15.macd_signal().iloc[-1]
    if direction == "BUY" and not (close15 > ema15 and slope_up and macd15_now > macd15_sig):
        return _skip("تأیید 15m برای BUY کامل نیست.")
    if direction == "SELL" and not (close15 < ema15 and not slope_up and macd15_now < macd15_sig):
        return _skip("تأیید 15m برای SELL کامل نیست.")

    # Avoid entering after an exhausted impulse: require room for the ATR
    # target without entering at an extreme Bollinger extension.
    if direction == "BUY" and d["bb_pband"] > 1.25:
        return _skip("BUY بیش از حد از باند بالایی Bollinger فاصله گرفته است.")
    if direction == "SELL" and d["bb_pband"] < -0.25:
        return _skip("SELL بیش از حد از باند پایینی Bollinger فاصله گرفته است.")

    divergence = d["divergence"]
    if (direction == "BUY" and divergence == "bearish") or (
        direction == "SELL" and divergence == "bullish"
    ):
        return _skip("واگرایی RSI خلاف جهت سیگنال است؛ ورود رد شد.")

    # Use the same signed score for both sides. The old implementation gave
    # the losing side exactly 0% and made the number look like a calibrated
    # probability. We now expose confidence plus a small neutral probability.
    opposite_score = -score
    buy_conf = confidence if direction == "BUY" else 100 - confidence
    sell_conf = confidence if direction == "SELL" else 100 - confidence
    neutral = max(0.0, 100.0 - max(buy_conf, sell_conf))

    return {
        "direction": direction,
        "buy": buy_conf,
        "sell": sell_conf,
        "neutral": neutral,
        "confidence": confidence,
        "atr": d["atr"],
        "price": price,
        "symbol": symbol,
        "adx": d["adx"],
        "di_plus": d["di_plus"],
        "di_minus": d["di_minus"],
        "rsi": d["rsi"],
        "divergence": divergence,
        "buy_ratio": d["buy_ratio"],
        "vwap": d["vwap"],
        "funding_rate": funding_rate,
        "liquidity_sweep": d["liquidity_sweep"],
        "fvg": d["fvg"],
        "score_breakdown": dict(sorted(d["components"].items(), key=lambda kv: abs(kv[1]), reverse=True)),
        "total_score": score,
        "atr_percent": atr_percent,
        "regime_4h": bias_4h,
        "regime_1d": bias_1d,
        "opposite_score": opposite_score,
    }
