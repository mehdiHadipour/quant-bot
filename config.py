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
# Time-stop — added after a real backtest showed a genuinely strong,
# validated pattern (unlike several other tested-and-rejected ideas: entry
# freshness, order-flow/CVD agreement, RSI extremity, distance from EMA,
# and a wider SL/TP all showed ~zero correlation with outcome on real
# data). Trades still under TIME_STOP_MIN_PROGRESS_R progress toward TP
# after TIME_STOP_HOURS averaged a real, final -0.33R outcome (32.5% win
# rate); trades that HAD reached that much progress by then averaged
# +0.42R (64.4% win rate) — a much larger, cleaner split than anything
# else tested. Interpreted as: fast resolution (either way) reflects
# market conviction; trades that just drift sideways for hours tend to
# keep drifting into a loss rather than recover. Re-validated with a real
# backtest re-run after implementing (see release notes) — not just this
# correlation check.
TIME_STOP_HOURS = _bounded_float_env("TIME_STOP_HOURS", 8.0, 0.0, 10000.0)
TIME_STOP_MIN_PROGRESS_R = _bounded_float_env("TIME_STOP_MIN_PROGRESS_R", 0.3, -10.0, 10.0)
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
CRYPTO_SYMBOLS = [s for s in SYMBOLS if s not in {"XAUUSDT","XAGUSDT","CLUSDT","NATGASUSDT"}]
COMMODITY_SYMBOLS = [s for s in SYMBOLS if s in {"XAUUSDT","XAGUSDT","CLUSDT","NATGASUSDT"}]
MAX_OPEN_PER_MARKET_GROUP = _positive_int_env("MAX_OPEN_PER_MARKET_GROUP", 2, minimum=0)
DIVERSIFICATION_ENABLED = os.getenv("DIVERSIFICATION_ENABLED", "true").strip().lower() in {"1","true","yes","on"}
