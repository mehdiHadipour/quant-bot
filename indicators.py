import math
import pandas as pd
import ta

def analyze_market(df_1h, df_4h, symbol):
    if len(df_1h) < 50 or len(df_4h) < 50:
        return None

    # Trend on 4H
    ema_50_4h = ta.trend.EMAIndicator(df_4h['close'], window=50).ema_indicator().iloc[-1]
    ema_200_4h = ta.trend.EMAIndicator(df_4h['close'], window=200).ema_indicator().iloc[-1]
    market_bias = "BULL" if ema_50_4h > ema_200_4h else "BEAR"

    # 1H analysis
    df = df_1h.copy()
    current_close = df['close'].iloc[-1]
    atr = ta.volatility.AverageTrueRange(high=df['high'], low=df['low'], close=df['close'], window=14).average_true_range().iloc[-1]
    atr_percent = (atr / current_close) * 100 if current_close > 0 else 0
    if atr_percent < 0.4:
        return None

    # Volume and BOS
    volume_ma = df['volume'].rolling(20).mean().iloc[-1]
    volume_ratio = df['volume'].iloc[-1] / volume_ma if volume_ma > 0 else 0
    prev_high = df['high'].iloc[-21:-1].max()
    prev_low = df['low'].iloc[-21:-1].min()

    structure_score = 0
    if current_close > prev_high and volume_ratio > 1.8:
        structure_score = 25
    elif current_close < prev_low and volume_ratio > 1.8:
        structure_score = -25

    # Other indicators
    rsi = ta.momentum.RSIIndicator(df['close'], window=14).rsi().iloc[-1]
    macd_indicator = ta.trend.MACD(df['close'])
    macd = macd_indicator.macd().iloc[-1]
    macd_signal = macd_indicator.macd_signal().iloc[-1]
    ema_50 = ta.trend.EMAIndicator(df['close'], window=50).ema_indicator().iloc[-1]
    ema_200 = ta.trend.EMAIndicator(df['close'], window=200).ema_indicator().iloc[-1]

    # Scoring
    trend_score = 10 if ema_50 > ema_200 else -10
    momentum_score = 10 if (macd > macd_signal and rsi < 70) else (-10 if rsi > 70 else 0)
    volume_score = 15 if volume_ratio > 1.5 else 0
    risk_score = 15 if atr_percent < 2.0 else 5

    total_score = (25 * (trend_score / 10)) + (20 * (momentum_score / 10)) + (15 * (volume_score / 15)) + (25 * (structure_score / 25)) + (15 * (risk_score / 15))

    # Probabilities
    buy_prob = 100 / (1 + math.exp(-abs(total_score) / 20)) if total_score > 0 else 0
    sell_prob = 100 / (1 + math.exp(abs(total_score) / 20)) if total_score < 0 else 0
    neutral_prob = 100 - buy_prob - sell_prob

    if market_bias == "BULL" and buy_prob > sell_prob:
        return {"direction": "BUY", "buy": buy_prob, "sell": sell_prob, "neutral": neutral_prob, "atr": atr, "price": current_close, "symbol": symbol}
    elif market_bias == "BEAR" and sell_prob > buy_prob:
        return {"direction": "SELL", "buy": buy_prob, "sell": sell_prob, "neutral": neutral_prob, "atr": atr, "price": current_close, "symbol": symbol}
    return None
