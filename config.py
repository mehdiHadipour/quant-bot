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
        "BTCUSDT,ETHUSDT,BNBUSDT,SOLUSDT,XRPUSDT,ADAUSDT,DOGEUSDT,AVAXUSDT,LINKUSDT,DOTUSDT,ZECUSDT,SUIUSDT,TONUSDT,NEARUSDT",
    ).split(",")
    if s.strip()
]

MIN_SIGNAL_PROBABILITY = _bounded_float_env("MIN_SIGNAL_PROBABILITY", 65.0, 0.0, 100.0)
MIN_ADX = _bounded_float_env("MIN_ADX", 25.0, 0.0, 100.0)
ATR_SL_MULTIPLIER = _bounded_float_env("ATR_SL_MULTIPLIER", 1.8, 0.1, 20.0)
ATR_TP_MULTIPLIER = _bounded_float_env("ATR_TP_MULTIPLIER", 3.0, 0.1, 50.0)
RISK_PERCENT_PER_TRADE = _bounded_float_env("RISK_PERCENT_PER_TRADE", 1.0, 0.01, 100.0)
SL_WARNING_THRESHOLD = _bounded_float_env("SL_WARNING_THRESHOLD", 0.8, 0.0, 1.0)
TRAILING_TRIGGER_R = _bounded_float_env("TRAILING_TRIGGER_R", 0.5, 0.0, 1.0)
PARTIAL_LOCK_TRIGGER_R = _bounded_float_env("PARTIAL_LOCK_TRIGGER_R", 0.75, 0.0, 1.0)
PARTIAL_LOCK_R = _bounded_float_env("PARTIAL_LOCK_R", 0.5, 0.0, 10.0)
CYCLE_MINUTES = _positive_int_env("CYCLE_MINUTES", 10, minimum=1)
SILENCE_GAP_MULTIPLIER = _bounded_float_env("SILENCE_GAP_MULTIPLIER", 6.0, 1.0, 100.0)
SYMBOL_COOLDOWN_CYCLES = _positive_int_env("SYMBOL_COOLDOWN_CYCLES", 6, minimum=0)
MAX_CONCURRENT_TRADES = _positive_int_env("MAX_CONCURRENT_TRADES", 4, minimum=0)
# Portfolio-level circuit breakers. Values are measured in R (initial risk units),
# so they remain meaningful without knowing the user's account balance.
MAX_DAILY_LOSS_R = _bounded_float_env("MAX_DAILY_LOSS_R", 3.0, 0.0, 100.0)
MAX_OPEN_RISK_R = _bounded_float_env("MAX_OPEN_RISK_R", 4.0, 0.0, 100.0)
MIN_REWARD_RISK = _bounded_float_env("MIN_REWARD_RISK", 1.5, 0.1, 20.0)
# Guards against concentrated directional risk across correlated symbols
# (see risk_engine.same_direction_open_count) rather than raw trade count.
MAX_SAME_DIRECTION_OPEN = _positive_int_env("MAX_SAME_DIRECTION_OPEN", 3, minimum=0)

# V28 Smart Context. External whale/news data are optional and fail-neutral.
SMART_CONTEXT_MODE = _str_env("SMART_CONTEXT_MODE", "live")
NEWS_ENABLED = _str_env("NEWS_ENABLED", "1")
NEWS_BLOCK_MINUTES = _positive_int_env("NEWS_BLOCK_MINUTES", 30, minimum=0)
MIN_HYPER_LIQUIDITY = _bounded_float_env("MIN_HYPER_LIQUIDITY", 35.0, 0.0, 100.0)
WHALE_BIAS_FILE = _str_env("WHALE_BIAS_FILE", "")
FUNDAMENTAL_FILE = _str_env("FUNDAMENTAL_FILE", "")


def _symbols_env(name):
    return {x.strip().upper() for x in _str_env(name, "").split(",") if x.strip()}

# Per-symbol directional policies. Leave empty unless deliberately validated
# by an out-of-sample study; this prevents accidental one-way restrictions.
BUY_ONLY_SYMBOLS = _symbols_env("BUY_ONLY_SYMBOLS")
SELL_ONLY_SYMBOLS = _symbols_env("SELL_ONLY_SYMBOLS")

# V30.4 session policy: Asia is enabled in addition to London/New York.
ASIA_ENABLED = _str_env("ASIA_ENABLED", "1")
ASIA_START = _str_env("ASIA_START", "09:00")
ASIA_END = _str_env("ASIA_END", "18:00")

# V30.6 adaptive session weighting and defensive per-symbol policy.
# These defaults are intentionally conservative; they can be overridden by
# GitHub Actions Variables without code changes.
SESSION_WEIGHTS = {
    "LONDON_NY_OVERLAP": 1.00,
    "ASIA_EUROPE_OVERLAP": 0.86,
    "LONDON": 0.88,
    "NEW_YORK": 0.92,
    "ASIA": 0.72,
}
STRICT_SYMBOLS = _symbols_env("STRICT_SYMBOLS") or {
    # Previous defensive set + LINKUSDT, which was also negative in V30.6.
    "ADAUSDT", "AVAXUSDT", "BTCUSDT", "DOGEUSDT", "DOTUSDT", "LINKUSDT", "SUIUSDT", "TONUSDT", "XRPUSDT", "ZECUSDT"
}
STRICT_MIN_SCORE = _bounded_float_env("STRICT_MIN_SCORE", 80.0, 0.0, 150.0)
STRICT_MIN_HLI = _bounded_float_env("STRICT_MIN_HLI", 70.0, 0.0, 100.0)
STRICT_REQUIRE_OTE = _str_env("STRICT_REQUIRE_OTE", "1")
STRICT_REQUIRE_MACD = _str_env("STRICT_REQUIRE_MACD", "1")
# Every live/backtest entry must be inside the directional Fibonacci OTE zone.
REQUIRE_FIB_OTE = _str_env("REQUIRE_FIB_OTE", "1")
FIB_LOOKBACK = _positive_int_env("FIB_LOOKBACK", 72, minimum=20)
FIB_OTE_LOW = _bounded_float_env("FIB_OTE_LOW", 0.618, 0.50, 0.90)
FIB_OTE_HIGH = _bounded_float_env("FIB_OTE_HIGH", 0.786, 0.60, 0.95)
COUNTERTREND_MIN_SCORE = _bounded_float_env("COUNTERTREND_MIN_SCORE", 82.0, 0.0, 150.0)
NEGATIVE_SESSIONS = _symbols_env("NEGATIVE_SESSIONS") or {"ASIA", "NEW_YORK"}
NEGATIVE_SESSION_MIN_SCORE = _bounded_float_env("NEGATIVE_SESSION_MIN_SCORE", 80.0, 0.0, 150.0)
NEGATIVE_SESSION_MIN_HLI = _bounded_float_env("NEGATIVE_SESSION_MIN_HLI", 70.0, 0.0, 100.0)


# V30.9.1 WEEX multi-asset research-first policy. TradFi candidates are discovered
# from WEEX V3, but remain isolated from live trading until an out-of-sample
# approval report explicitly promotes them.
TRADFI_ENABLED = _str_env("TRADFI_ENABLED", "1")
TRADFI_LIVE_APPROVAL_REQUIRED = _str_env("TRADFI_LIVE_APPROVAL_REQUIRED", "1")
TRADFI_APPROVED_SYMBOLS = _str_env("TRADFI_APPROVED_SYMBOLS", "")
TRADFI_APPROVAL_FILE = _str_env("TRADFI_APPROVAL_FILE", "state/tradfi_approval.json")
TRADFI_BACKTEST_DAYS = _positive_int_env("TRADFI_BACKTEST_DAYS", 90, minimum=7)
TRADFI_MIN_TRADES = _positive_int_env("TRADFI_MIN_TRADES", 30, minimum=1)
TRADFI_MIN_PF = _bounded_float_env("TRADFI_MIN_PF", 1.25, 0.5, 10.0)
TRADFI_MAX_DD_R = _bounded_float_env("TRADFI_MAX_DD_R", 8.0, 0.5, 100.0)
