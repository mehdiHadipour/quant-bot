"""Configuration for the quant bot.

The module is intentionally import-safe: unit tests and tooling can import the
code without Telegram/crypto secrets. Production startup calls
``validate_runtime_secrets()`` before any network or state operation.
"""
import os
from dotenv import load_dotenv
from logger import log

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT = os.getenv("TELEGRAM_CHAT", "")
ENCRYPTION_KEY = os.getenv("ENCRYPTION_KEY", "")


def validate_runtime_secrets() -> None:
    """Fail closed at runtime, but never during module import/test discovery."""
    missing = [
        name for name, value in (
            ("TELEGRAM_TOKEN", TELEGRAM_TOKEN),
            ("TELEGRAM_CHAT", TELEGRAM_CHAT),
            ("ENCRYPTION_KEY", ENCRYPTION_KEY),
        ) if not value.strip()
    ]
    if missing:
        raise RuntimeError(
            "Missing required runtime secrets: " + ", ".join(missing) +
            ". Configure them as GitHub Actions Secrets; never commit them."
        )


def _float_env(name, default):
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return float(raw)
    except ValueError:
        log.warning("Invalid %s=%r; using default %s", name, raw, default)
        return default


def _bounded_float_env(name, default, low, high):
    value = _float_env(name, default)
    if not low <= value <= high:
        log.warning("%s=%s outside [%s,%s]; using default %s", name, value, low, high, default)
        return default
    return value


def _positive_int_env(name, default, minimum=0):
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        value = int(raw)
    except ValueError:
        log.warning("Invalid %s=%r; using default %s", name, raw, default)
        return default
    if value < minimum:
        log.warning("Invalid %s=%r; using default %s", name, raw, default)
        return default
    return value


def _str_env(name, default):
    raw = os.getenv(name)
    return default if raw is None or not raw.strip() else raw


SYMBOLS = [
    s.strip().upper()
    for s in _str_env(
        "SYMBOLS",
        "BTCUSDT,ETHUSDT,BNBUSDT,SOLUSDT,XRPUSDT,ADAUSDT,DOGEUSDT,AVAXUSDT,LINKUSDT,DOTUSDT,ZECUSDT,SUIUSDT,TONUSDT,NEARUSDT,XAUUSDT,XAGUSDT,CLUSDT,NATGASUSDT",
    ).split(",")
    if s.strip()
]

MIN_SIGNAL_PROBABILITY = _bounded_float_env("MIN_SIGNAL_PROBABILITY", 70.0, 0.0, 100.0)
MIN_ADX = _bounded_float_env("MIN_ADX", 25.0, 0.0, 100.0)
ATR_SL_MULTIPLIER = _bounded_float_env("ATR_SL_MULTIPLIER", 1.8, 0.1, 20.0)
# Backtest-informed change (was 3.0): an approximate re-simulation using
# real backtest_results.csv trade data (each closed trade's actual
# maximum-favorable-excursion toward the OLD 3.0xATR target, from a
# real user-run backtest — see RELEASE_NOTES for the full table) showed
# a materially better historical expectancy around a MUCH closer target
# than 3.0xATR: win rate rose from ~19% to ~46% at 1.8xATR (a 1:1
# reward:risk), turning an aggregately losing sample strongly positive
# in that approximation. NOT a guarantee — re-validate with a real
# scripts/run_backtest.py re-run (not just the approximation) before
# trusting this with real capital; the approximation has a known bias
# (see release notes) that likely overstates the benefit somewhat, but
# the underlying signal (this strategy's price moves are far shorter/
# choppier than a 1.67:1-reward setup assumes) is real and visible
# directly in the MFE data, not just this one estimate.
ATR_TP_MULTIPLIER = _bounded_float_env("ATR_TP_MULTIPLIER", 1.8, 0.1, 50.0)
RISK_PERCENT_PER_TRADE = _bounded_float_env("RISK_PERCENT_PER_TRADE", 1.0, 0.01, 100.0)
SL_WARNING_THRESHOLD = _bounded_float_env("SL_WARNING_THRESHOLD", 0.8, 0.0, 1.0)
TRAILING_TRIGGER_R = _bounded_float_env("TRAILING_TRIGGER_R", 0.5, 0.0, 1.0)
PARTIAL_LOCK_TRIGGER_R = _bounded_float_env("PARTIAL_LOCK_TRIGGER_R", 0.75, 0.0, 1.0)
PARTIAL_LOCK_R = _bounded_float_env("PARTIAL_LOCK_R", 0.5, 0.0, 10.0)
# Third trailing-stop tier (V27.20) — added after a real backtest
# re-simulation (not just an MFE-based estimate) showed trades that got
# extremely close to TP (>=90% of the way there) and then reversed were
# still only banking Stage 2's flat 0.5R, when they'd earned much more
# of the move. See trade_monitor.check_trailing_stop's docstring.
NEAR_TP_LOCK_TRIGGER_R = _bounded_float_env("NEAR_TP_LOCK_TRIGGER_R", 0.90, 0.0, 2.0)
NEAR_TP_LOCK_R = _bounded_float_env("NEAR_TP_LOCK_R", 0.70, 0.0, 10.0)


def _parse_time_stop_schedule(raw, default):
    """Parses 'hours:min_progress_r,hours:min_progress_r,...' into a
    sorted list of (hours, min_progress_r) tuples. Falls back to
    `default` (already such a list) on any parse error or empty input —
    this schedule is a decay of increasingly demanding checkpoints as a
    trade ages, so a malformed value should never silently disable it or
    crash startup."""
    if not raw or not raw.strip():
        return default
    try:
        checkpoints = []
        for part in raw.split(","):
            hours_str, progress_str = part.split(":")
            checkpoints.append((float(hours_str), float(progress_str)))
        if not checkpoints:
            return default
        return sorted(checkpoints, key=lambda c: c[0])
    except (ValueError, IndexError):
        log.warning("Invalid TIME_STOP_SCHEDULE=%r; using default %s", raw, default)
        return default


# Graduated time-stop (V27.19) — a decay schedule of increasingly
# demanding checkpoints, replacing V27.18's single (8h, 0.3R) threshold.
# NostalgiaForInfinity (a widely-used, community-vetted Freqtrade
# strategy researched this round) uses the same core idea — a time-based
# ROI table where the minimum acceptable profit rises as a trade ages —
# so this generalizes V27.18's single checkpoint into the same shape.
#
# Both checkpoints below are independently backtest-validated (not just
# the second one, carried over from V27.18): at 4h, trades under 0.10R
# progress averaged a real -0.35R final outcome vs +0.29R for trades that
# had reached it; at 8h, under 0.30R averaged -0.33R vs +0.42R. The
# schedule deliberately stops at 8h — a 32-64h duration bucket in the
# same data showed trades surviving that long swung back to a small
# POSITIVE average outcome, so extending this decay further is not
# supported by what's actually been tested; don't add later checkpoints
# without validating them the same way first.
#
# At evaluation time, the LATEST checkpoint whose hour threshold the
# trade has already passed is the one that applies (e.g. a 10-hour-old
# trade is judged against the 8h checkpoint, not the 4h one) — so later,
# more demanding checkpoints supersede earlier ones as a trade ages.
TIME_STOP_SCHEDULE = _parse_time_stop_schedule(
    os.getenv("TIME_STOP_SCHEDULE"), default=[(4.0, 0.10), (8.0, 0.30)]
)
CYCLE_MINUTES = _positive_int_env("CYCLE_MINUTES", 10, minimum=1)
SILENCE_GAP_MULTIPLIER = _bounded_float_env("SILENCE_GAP_MULTIPLIER", 6.0, 1.0, 100.0)
SYMBOL_COOLDOWN_CYCLES = _positive_int_env("SYMBOL_COOLDOWN_CYCLES", 6, minimum=0)
MAX_CONCURRENT_TRADES = _positive_int_env("MAX_CONCURRENT_TRADES", 4, minimum=0)
# Portfolio-level circuit breakers. Values are measured in R (initial risk units),
# so they remain meaningful without knowing the user's account balance.
MAX_DAILY_LOSS_R = _bounded_float_env("MAX_DAILY_LOSS_R", 3.0, 0.0, 100.0)
MAX_OPEN_RISK_R = _bounded_float_env("MAX_OPEN_RISK_R", 4.0, 0.0, 100.0)
# Lowered alongside ATR_TP_MULTIPLIER's reduction (was 1.5) — with TP now
# at 1.8xATR / SL at 1.8xATR (a 1:1 ratio), a 1.5 minimum would reject
# every single trade this strategy could ever produce. See
# ATR_TP_MULTIPLIER's comment for the backtest data behind this change.
MIN_REWARD_RISK = _bounded_float_env("MIN_REWARD_RISK", 1.0, 0.1, 20.0)
# Guards against concentrated directional risk across correlated symbols
# (see risk_engine.same_direction_open_count) rather than raw trade count.
MAX_SAME_DIRECTION_OPEN = _positive_int_env("MAX_SAME_DIRECTION_OPEN", 3, minimum=0)

# V27.12 Hybrid AdaptiveTrend overlay (from V31 research)
ADAPTIVE_TREND_ENABLED = os.getenv("ADAPTIVE_TREND_ENABLED", "true").strip().lower() in {"1","true","yes","on"}
ADAPTIVE_FAST_EMA = _positive_int_env("ADAPTIVE_FAST_EMA", 6, minimum=2)
ADAPTIVE_SLOW_EMA = _positive_int_env("ADAPTIVE_SLOW_EMA", 18, minimum=3)
ADAPTIVE_TARGET_VOL = _bounded_float_env("ADAPTIVE_TARGET_VOL", 0.20, 0.01, 5.0)
ADAPTIVE_MAX_ASSET_WEIGHT = _bounded_float_env("ADAPTIVE_MAX_ASSET_WEIGHT", 1.0, 0.05, 1.0)
ADAPTIVE_MIN_RV = _bounded_float_env("ADAPTIVE_MIN_RV", 0.10, 0.0, 5.0)
ADAPTIVE_MAX_RV = _bounded_float_env("ADAPTIVE_MAX_RV", 2.00, 0.01, 10.0)


# V27.13 Multi-Market diversification. Commodity symbols are fetched from
# WEEX contract market data; crypto symbols keep the Binance/Bybit stack.
# Classification reuses data_engine.WEEX_COMMODITY_SYMBOLS (see that
# module's comment — it also lists unverified candidate index/stock
# tickers researched for V27.19; only symbols actually present in SYMBOLS
# get classified, so adding an unverified ticker here has no effect
# until it's also added to SYMBOLS).
from data_engine import WEEX_COMMODITY_SYMBOLS as _WEEX_SYMBOLS
CRYPTO_SYMBOLS = [s for s in SYMBOLS if s not in _WEEX_SYMBOLS]
COMMODITY_SYMBOLS = [s for s in SYMBOLS if s in _WEEX_SYMBOLS]
MAX_OPEN_PER_MARKET_GROUP = _positive_int_env("MAX_OPEN_PER_MARKET_GROUP", 2, minimum=0)
DIVERSIFICATION_ENABLED = os.getenv("DIVERSIFICATION_ENABLED", "true").strip().lower() in {"1","true","yes","on"}
