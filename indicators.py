import math
import pandas as pd
import ta

from logger import log
from smart_context import smart_context, load_whale_bias, fundamental_score

from config import (
    MIN_SIGNAL_PROBABILITY, MIN_ADX, ADAPTIVE_TREND_ENABLED,
    ADAPTIVE_FAST_EMA, ADAPTIVE_SLOW_EMA, ADAPTIVE_TARGET_VOL,
    ADAPTIVE_MAX_ASSET_WEIGHT, ADAPTIVE_MIN_RV, ADAPTIVE_MAX_RV,
    SMART_CONTEXT_ENABLED, SMART_CONTEXT_MIN_SCORE, WHALE_FILTER_ENABLED,
    FUNDAMENTAL_FILTER_ENABLED, SESSION_FILTER_ENABLED, FOOTPRINT_HARD_FILTER,
    FUNDAMENTAL_HARD_VETO,
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


def analyze_market(df_15m, df_1h, df_4h, df_1d, symbol, funding_rate=None, reasons=None, footprint_metrics=None, timestamp=None, headlines=None):
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

    # --- Diagnostic-only values shared by BOTH return paths below (the
    # AdaptiveTrend early-return and the legacy scoring path further down).
    # BUG FIX (found via CI lint's F821 "undefined name" check): these were
    # previously computed only in the legacy path, AFTER the
    # ADAPTIVE_TREND_ENABLED early-return already referenced them in its
    # result dict — since ADAPTIVE_TREND_ENABLED defaults to true (the
    # primary strategy per README), this meant every single call to
    # analyze_market() crashed with NameError under default settings, and
    # the bot could never produce a signal. Computed here instead, using
    # only data already available at this point (df, rsi_series,
    # current_taker_buy_volume, current_volume) — legacy path below reuses
    # these same variables rather than recomputing them.
    divergence = detect_rsi_divergence(df['close'], rsi_series)
    prev_high = df['high'].iloc[-21:-1].max()
    prev_low = df['low'].iloc[-21:-1].min()
    liquidity_sweep = None
    swept_sell_side = current_low < prev_low
    swept_buy_side = current_high > prev_high
    if swept_sell_side and current_close > prev_low:
        liquidity_sweep = "bullish"
    elif swept_buy_side and current_close < prev_high:
        liquidity_sweep = "bearish"
    buy_ratio = current_taker_buy_volume / current_volume if current_volume > 0 else 0.5

    # V27.30 context fusion: entry location, order-flow/footprint, session,
    # optional whale bias and optional fundamental headlines. Missing external
    # data is neutral; no provider can create a trade by itself.
    whale_s, whale_reason = load_whale_bias(symbol, "BUY") if WHALE_FILTER_ENABLED else (0, "disabled")
    # Re-score whale for the actual direction after direction is known; the
    # provisional BUY read above is intentionally not used as a signal.
    smart_pre = {"score": 0, "whale_score": 0, "fundamental_score": 0}

    # V27.12 Hybrid: the strongest research component from V31 is used as
    # the primary regime engine. 4H EMA(6/18) supplies direction and a
    # 30-day 4H realized-volatility regime controls whether the trend is
    # tradeable. Legacy V27 scoring remains available by setting
    # ADAPTIVE_TREND_ENABLED=false.
    if ADAPTIVE_TREND_ENABLED:
        fast_a = ta.trend.EMAIndicator(df_4h["close"], window=ADAPTIVE_FAST_EMA).ema_indicator().iloc[-1]
        slow_a = ta.trend.EMAIndicator(df_4h["close"], window=ADAPTIVE_SLOW_EMA).ema_indicator().iloc[-1]
        rv_4h = (
            df_4h["close"].pct_change()
            .rolling(180)
            .std()
            * math.sqrt(6 * 365)
        ).iloc[-1]
        if pd.isna(fast_a) or pd.isna(slow_a) or pd.isna(rv_4h):
            return _skip("AdaptiveTrend: دادهٔ کافی برای EMA/نوسان 30روزه وجود ندارد")
        if rv_4h < ADAPTIVE_MIN_RV:
            return _skip(f"AdaptiveTrend: نوسان سالانه {rv_4h:.2f} < حداقل {ADAPTIVE_MIN_RV:.2f}")
        if rv_4h > ADAPTIVE_MAX_RV:
            return _skip(f"AdaptiveTrend: نوسان سالانه {rv_4h:.2f} > حداکثر {ADAPTIVE_MAX_RV:.2f}")
        # Trend-quality gate — added after reviewing a real backtest
        # (backtest_results.csv): the AdaptiveTrend path previously had NO
        # trend-strength filter at all, only the volatility-regime bounds
        # above. A bare EMA(6)/EMA(18) crossover flips direction on every
        # wiggle in a genuinely trendless/choppy market. The legacy
        # scoring path already requires ADX >= MIN_ADX for exactly this
        # reason, but the AdaptiveTrend path never did.
        #
        # BUG FIX (found by re-running the backtest after the first
        # attempt at this fix barely moved the win rate: 13.7% -> 13.3%,
        # nowhere near enough): the first version of this gate reused the
        # module-level `adx` variable, which is computed from `df` — the
        # 1H timeframe. But this signal's direction comes entirely from
        # 4H EMAs (fast_a/slow_a above); filtering a 4H trend decision by
        # 1H trend strength is a timeframe mismatch — 1H can look choppy
        # while 4H is genuinely trending, and vice versa, so the filter
        # wasn't actually screening the thing that matters. Computing ADX
        # on df_4h instead, to match the timeframe the direction itself
        # comes from.
        # IMPORTANT: still a reasoned hypothesis, not a guarantee — this
        # is now the SECOND attempt at addressing the same backtest
        # finding, which is itself evidence that fixing this kind of
        # strategy issue by inspection alone is unreliable. Re-run
        # scripts/run_backtest.py after this change and compare the win
        # rate/expectancy again before trusting it with real capital. If
        # this still doesn't move the win rate meaningfully, the more
        # likely explanation is that a bare EMA(6)/EMA(18) crossover
        # doesn't have a viable edge on these instruments/period at all,
        # regardless of which timeframe's ADX gates it — at that point,
        # the fix that actually needs testing is adding real confirmation
        # (e.g. the same 15m+1H+4H+1D multi-timeframe confluence the
        # legacy path already uses), not another single-filter tweak.
        adx_4h = ta.trend.ADXIndicator(
            high=df_4h["high"], low=df_4h["low"], close=df_4h["close"], window=14
        ).adx().iloc[-1]
        if pd.isna(adx_4h):
            return _skip("AdaptiveTrend: ADX چهارساعته قابل محاسبه نبود")
        if adx_4h < MIN_ADX:
            return _skip(f"AdaptiveTrend: ADX چهارساعته {adx_4h:.1f} < حداقل {MIN_ADX:.1f} — روند به‌اندازهٔ کافی قوی نیست")
        adaptive_direction = "BUY" if fast_a > slow_a else "SELL"

        # Multi-timeframe confluence — the real next step flagged after two
        # rounds of single-filter tweaks (1H ADX, then 4H ADX) both failed
        # to move the win rate on a real backtest (13.7% -> 13.3% -> 12.9%,
        # i.e. no meaningful improvement, sometimes worse). That outcome is
        # itself evidence the bare 4H EMA(6)/EMA(18) crossover doesn't have
        # a reliable standalone edge — the legacy scoring path never relies
        # on a single timeframe either; it requires higher-timeframe trend
        # agreement before treating a signal as real. This adds the same
        # kind of top-down check: skip if the 1D trend (EMA50 vs EMA200,
        # via the existing get_timeframe_bias helper) contradicts the 4H
        # signal's own direction. Fails OPEN, not closed, when 1D history
        # is insufficient (get_timeframe_bias returns None) — consistent
        # with how funding_rate and other optional confirmations already
        # behave elsewhere in this function: a missing higher-timeframe
        # opinion should never itself block a signal, only an opinion
        # that actively disagrees should.
        # IMPORTANT: still an unproven, reasoned hypothesis — this is now
        # the THIRD change made in response to the same backtest finding.
        # Re-run scripts/run_backtest.py again after this and look at the
        # win rate before trusting any of this with real capital. If this
        # STILL doesn't help, the honest conclusion is that this signal
        # (in its current form) may not have a tradeable edge on this
        # data at all, and no further single-mechanism patch should be
        # trusted without out-of-sample validation (see
        # scripts/validate_robustness.py from an earlier round) first.
        daily_bias = get_timeframe_bias(df_1d)
        if daily_bias is not None:
            expected_bias = "BULL" if adaptive_direction == "BUY" else "BEAR"
            if daily_bias != expected_bias:
                return _skip(
                    f"AdaptiveTrend: جهت {adaptive_direction} با روند روزانه ({daily_bias}) هم‌خوانی ندارد"
                )

        adaptive_weight = min(ADAPTIVE_TARGET_VOL / max(rv_4h, 1e-9), ADAPTIVE_MAX_ASSET_WEIGHT)
        whale_score, whale_reason = load_whale_bias(symbol, adaptive_direction) if WHALE_FILTER_ENABLED else (0, "disabled")
        fund_score, fund_reason = fundamental_score(symbol, adaptive_direction, headlines) if FUNDAMENTAL_FILTER_ENABLED else (0, "disabled")
        ctx = smart_context(df_15m, df, adaptive_direction, footprint_metrics=footprint_metrics, timestamp=timestamp, whale_score=whale_score, fundamental_score_value=fund_score)
        if SESSION_FILTER_ENABLED and ctx["weekend"] and ctx["session_score"] < 0:
            ctx["score"] -= 1
        if FUNDAMENTAL_FILTER_ENABLED and fund_score <= -FUNDAMENTAL_HARD_VETO:
            return _skip(f"AdaptiveTrend: خبر بنیادی شدیداً مخالف جهت ({fund_score})")
        if SMART_CONTEXT_ENABLED and ctx["score"] < SMART_CONTEXT_MIN_SCORE:
            return _skip(f"SmartContext: امتیاز زمینه {ctx['score']} < حداقل {SMART_CONTEXT_MIN_SCORE}")
        if FOOTPRINT_HARD_FILTER and ctx["footprint_score"] < 0:
            return _skip("Footprint: فشار سفارشات خلاف جهت ورود")
        return {
            "symbol": symbol,
            "direction": adaptive_direction,
            "buy": 100.0 if adaptive_direction == "BUY" else 0.0,
            "sell": 100.0 if adaptive_direction == "SELL" else 0.0,
            "atr": atr,
            "adx": adx,
            "buy_ratio": buy_ratio,
            "vwap": vwap,
            "fvg": fvg,
            "liquidity_sweep": liquidity_sweep,
            "divergence": divergence,
            "total_score": 100.0 if adaptive_direction == "BUY" else -100.0,
            "score_breakdown": {
                "Adaptive EMA 4H": 60 if adaptive_direction == "BUY" else -60,
                "Volatility Target": adaptive_weight * 40 * (1 if adaptive_direction == "BUY" else -1),
            },
            "adaptive_rv": rv_4h,
            "adaptive_weight": adaptive_weight,
            "smart_context": ctx,
            "whale_reason": whale_reason,
            "fundamental_reason": fund_reason,
        }

    # --- Hard filter: skip ranging / weak-trend markets ---
    # ADX below the configured threshold means there is no meaningful trend
    # to trade with (classic "choppy market" condition), regardless of how
    # the other scores look.
    if adx < MIN_ADX:
        return _skip(f"ADX {adx:.1f} < حداقل {MIN_ADX} → بازار رنج/بدون روند کافی است")

    market_bias = "BULL" if ema_50_4h > ema_200_4h else "BEAR"

    atr_percent = (atr / current_close) * 100
    if atr_percent < 0.5:
        return _skip(f"نوسان خیلی کم است (ATR {atr_percent:.2f}٪ < حداقل 0.5٪)")

    # Volume and break-of-structure
    volume_ratio = df['volume'].iloc[-1] / volume_ma if volume_ma > 0 else 0
    # prev_high/prev_low computed earlier (shared with the AdaptiveTrend
    # path's liquidity_sweep calculation above); reused here unchanged.

    structure_score = 0
    breakout_up = current_close > prev_high and volume_ratio > 1.8
    breakout_down = current_close < prev_low and volume_ratio > 1.8
    if breakout_up:
        structure_score = 25
    elif breakout_down:
        structure_score = -25

    # --- ICT-style Liquidity Sweep score: liquidity_sweep itself
    # (bullish/bearish/None) is already computed above, shared with the
    # AdaptiveTrend path; sweep_score is legacy-scoring-only so it stays
    # here, mutually exclusive with structure_score by construction
    # (breakout needs the CLOSE beyond the level; a sweep needs the close
    # back INSIDE it), so it can never double-count with structure_score
    # for the same candle.
    sweep_score = 0
    if liquidity_sweep == "bullish":
        sweep_score = 12
    elif liquidity_sweep == "bearish":
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
    # tick-level trade data. buy_ratio itself is computed earlier, shared
    # with the AdaptiveTrend path; order_flow_score is legacy-scoring-only.
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

    total_score = (
        trend_score
        + momentum_score
        + stoch_score
        + volume_score
        + structure_score
        + bb_score
        + risk_score
        + wick_score
        + order_flow_score
        + vwap_score
        + fvg_score
        + funding_score
        + sweep_score
    )

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
    if market_bias == "BULL" and buy_prob > sell_prob and buy_prob >= MIN_SIGNAL_PROBABILITY:
        direction = "BUY"
    elif market_bias == "BEAR" and sell_prob > buy_prob and sell_prob >= MIN_SIGNAL_PROBABILITY:
        direction = "SELL"

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
    if daily_bias is None or daily_bias != market_bias:
        return _skip(
            f"سیگنال {direction} روی 4H تشخیص داده شد اما تأیید 1D نشد "
            f"(بایاس 1D: {daily_bias or 'دادهٔ ناکافی'} در برابر بایاس 4H: {market_bias})"
        )

    # 15m short-term confirmation: don't enter if the very short-term
    # momentum is already pointing the other way (e.g. a BUY signal right
    # as the 15m chart is rolling over). Kept intentionally simple — a
    # single EMA20 check, not a full second scoring system.
    if len(df_15m) >= 20:
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

    # V27.30 Smart Context for the legacy scorer too.
    whale_score, whale_reason = load_whale_bias(symbol, direction) if WHALE_FILTER_ENABLED else (0, "disabled")
    fund_score, fund_reason = fundamental_score(symbol, direction, headlines) if FUNDAMENTAL_FILTER_ENABLED else (0, "disabled")
    ctx = smart_context(df_15m, df, direction, footprint_metrics=footprint_metrics, timestamp=timestamp, whale_score=whale_score, fundamental_score_value=fund_score)
    if SESSION_FILTER_ENABLED and ctx["weekend"] and ctx["session_score"] < 0:
        ctx["score"] -= 1
    if FUNDAMENTAL_FILTER_ENABLED and fund_score <= -FUNDAMENTAL_HARD_VETO:
        return _skip(f"خبر بنیادی شدیداً مخالف جهت ({fund_score})")
    if SMART_CONTEXT_ENABLED and ctx["score"] < SMART_CONTEXT_MIN_SCORE:
        return _skip(f"SmartContext: امتیاز زمینه {ctx['score']} < حداقل {SMART_CONTEXT_MIN_SCORE}")
    if FOOTPRINT_HARD_FILTER and ctx["footprint_score"] < 0:
        return _skip("Footprint: فشار سفارشات خلاف جهت ورود")
    total_score += ctx["score"]

    # v27.8: a compact breakdown of which factors contributed to the
    # score, so a FIRED signal's reasoning is visible too — not just the
    # no-signal diagnostics added in v25.2. Requested after real trades
    # (e.g. the DOTUSDT case) raised "why did this fire?" questions that
    # were hard to answer from the alert message alone. Only the
    # non-zero components are kept (a zero contributor adds no
    # information and just clutters the message); sorted by magnitude so
    # the biggest drivers of the decision are listed first.
    score_breakdown = {
        "Trend (EMA)": trend_score, "Momentum (RSI)": momentum_score,
        "Stochastic": stoch_score, "Volume": volume_score,
        "Structure/Breakout": structure_score, "Bollinger": bb_score,
        "Risk/Volatility": risk_score, "Wick Rejection": wick_score,
        "Order Flow": order_flow_score, "VWAP": vwap_score,
        "FVG": fvg_score, "Funding Rate": funding_score,
        "Liquidity Sweep": sweep_score,
    }
    score_breakdown = {k: v for k, v in score_breakdown.items() if v != 0}
    score_breakdown = dict(sorted(score_breakdown.items(), key=lambda kv: abs(kv[1]), reverse=True))

    return {"direction": direction, "buy": buy_prob, "sell": sell_prob, "neutral": neutral_prob, "atr": atr, "price": current_close, "symbol": symbol, "adx": adx, "divergence": divergence, "buy_ratio": buy_ratio, "fvg": fvg, "vwap": vwap, "funding_rate": funding_rate, "liquidity_sweep": liquidity_sweep, "score_breakdown": score_breakdown, "total_score": total_score, "smart_context": ctx, "whale_reason": whale_reason, "fundamental_reason": fund_reason}
