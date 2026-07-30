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

MIN_SIGNAL_PROBABILITY = _bounded_float_env("MIN_SIGNAL_PROBABILITY", 70.0, 0.0, 100.0)
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
