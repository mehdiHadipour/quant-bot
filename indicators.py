import math
import pandas as pd
import ta

from logger import log

from config import MIN_SIGNAL_PROBABILITY, MIN_ADX

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


def analyze_market(df_15m, df_1h, df_4h, df_1d, symbol):
    if len(df_1h) < MIN_CANDLES or len(df_4h) < MIN_CANDLES:
        return None

    df = df_1h.copy()

    # --- Trend on 4H ---
    ema_50_4h = ta.trend.EMAIndicator(df_4h['close'], window=50).ema_indicator().iloc[-1]
    ema_200_4h = ta.trend.EMAIndicator(df_4h['close'], window=200).ema_indicator().iloc[-1]

    # --- 1H core indicators ---
    current_close = df['close'].iloc[-1]
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

    # If any indicator came back NaN (can happen with gappy/incomplete
    # candle data from the exchange), bail out instead of risking a
    # comparison against NaN, which silently evaluates to False and could
    # produce a misleading signal rather than an obvious error.
    critical_values = [
        ema_50_4h, ema_200_4h, current_close, atr, volume_ma, rsi, macd, macd_signal,
        ema_50, ema_200, adx, bb_pband, stoch, stoch_signal,
    ]
    if any(pd.isna(v) for v in critical_values):
        log.warning(f"{symbol}: insufficient/incomplete indicator data this cycle, skipping.")
        return None

    if current_close <= 0:
        return None

    # --- Hard filter: skip ranging / weak-trend markets ---
    # ADX below the configured threshold means there is no meaningful trend
    # to trade with (classic "choppy market" condition), regardless of how
    # the other scores look.
    if adx < MIN_ADX:
        return None

    divergence = detect_rsi_divergence(df['close'], rsi_series)

    market_bias = "BULL" if ema_50_4h > ema_200_4h else "BEAR"

    atr_percent = (atr / current_close) * 100
    if atr_percent < 0.5:
        return None

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

    # --- Scoring (weights sum to 100, same scale as before so the
    # probability sigmoid below stays calibrated) ---
    trend_score = 20 if ema_50 > ema_200 else -20
    momentum_score = 15 if (macd > macd_signal and 30 < rsi < 70) else (-15 if rsi > 70 else 0)
    volume_score = 10 if volume_ratio > 1.5 else 0

    total_score = (
        trend_score
        + momentum_score
        + stoch_score
        + volume_score
        + structure_score
        + bb_score
        + (15 if atr_percent < 2.0 else 5)  # risk_score, same as before
    )

    # Probabilities
    buy_prob = 100 / (1 + math.exp(-abs(total_score) / 20)) if total_score > 0 else 0
    sell_prob = 100 / (1 + math.exp(abs(total_score) / 20)) if total_score < 0 else 0
    neutral_prob = 100 - buy_prob - sell_prob

    # Weak-signal filter: only act on signals whose probability clears the
    # configured confidence bar (default 60%), on top of the market-bias
    # agreement check that was already required.
    direction = None
    if market_bias == "BULL" and buy_prob > sell_prob and buy_prob >= MIN_SIGNAL_PROBABILITY:
        direction = "BUY"
    elif market_bias == "BEAR" and sell_prob > buy_prob and sell_prob >= MIN_SIGNAL_PROBABILITY:
        direction = "SELL"

    if direction is None:
        return None

    # --- Multi-timeframe confluence (quality over quantity) ---
    # 1D trend must agree with the 4H trend bias that produced this signal;
    # if the daily chart disagrees, this is a lower-conviction counter-trend
    # setup on the bigger picture and is skipped rather than traded.
    daily_bias = get_timeframe_bias(df_1d)
    if daily_bias is None or daily_bias != market_bias:
        return None

    # 15m short-term confirmation: don't enter if the very short-term
    # momentum is already pointing the other way (e.g. a BUY signal right
    # as the 15m chart is rolling over). Kept intentionally simple — a
    # single EMA20 check, not a full second scoring system.
    if len(df_15m) >= 20:
        ema_20_15m = ta.trend.EMAIndicator(df_15m['close'], window=20).ema_indicator().iloc[-1]
        current_15m_close = df_15m['close'].iloc[-1]
        if not pd.isna(ema_20_15m):
            if direction == "BUY" and current_15m_close < ema_20_15m:
                return None
            if direction == "SELL" and current_15m_close > ema_20_15m:
                return None

    return {"direction": direction, "buy": buy_prob, "sell": sell_prob, "neutral": neutral_prob, "atr": atr, "price": current_close, "symbol": symbol, "adx": adx, "divergence": divergence}
