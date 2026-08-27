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


# Core markets are always present so BTC/ETH cannot be accidentally removed
# by a stale GitHub SYMBOLS variable. All configured symbols remain tradable
# in BOTH directions by default.
CORE_SYMBOLS = ("BTCUSDT", "ETHUSDT")
_symbol_list = [
    s.strip().upper()
    for s in _str_env(
        "SYMBOLS",
        "BTCUSDT,ETHUSDT,BNBUSDT,SOLUSDT,XRPUSDT,ADAUSDT,DOGEUSDT,AVAXUSDT,LINKUSDT,DOTUSDT,ZECUSDT,SUIUSDT,TONUSDT,NEARUSDT",
    ).split(",")
    if s.strip()
]
SYMBOLS = list(dict.fromkeys(_symbol_list + list(CORE_SYMBOLS)))

# --- WEEX "TradFi" tokenized products (gold, oil/gas, forex, tokenized US
# stocks, indices), fetched via weex_data_engine instead of Binance. This
# default list was built from the user's own WEEX app screenshots (2026-08-27)
# covering every TradFi sub-tab: کالاها (commodities), فلزات (metals), فارکس
# (forex), سهام (stocks), شاخص‌ها (indices), Pre-IPO.
#
# WEEX lists several *duplicate* instruments for the same underlying asset
# (e.g. gold as XAUUSDT, GOLD(XAUT)USDT, and GOLD(PAXG)USDT all at once) --
# only one representative per asset is kept here to avoid three near-identical
# correlated signals firing for the same move. The full confirmed list is
# documented in the README; add any of them via the WEEX_SYMBOLS repo
# variable. Adding all ~37 at once would roughly triple every 5-minute
# cycle's request count against the current 8-minute job timeout, so this
# default is deliberately a curated "top pick per category", not the full set.
#
# XAGUSDT (silver) is the one inferred-not-directly-confirmed entry here: WEEX
# shows it in the app as "SILVER(XAG)USDT", and every other paren-labeled
# instrument observed (GOLD(PAXG)USDT -> PAXGUSDT, GOLD(XAUT)USDT -> XAUTUSDT)
# follows a confirmed "ticker in parens = the real API symbol" pattern, but
# XAGUSDT itself wasn't independently seen written out plainly. It fails soft
# (skips that symbol, logs a warning) if the ticker turns out to be wrong.
WEEX_ENABLED = _str_env("WEEX_ENABLED", "1").strip().lower() not in {"0", "false", "no", "off"}
_weex_symbol_list = [
    s.strip().upper()
    for s in _str_env(
        "WEEX_SYMBOLS",
        # Metals: gold, silver, copper
        "XAUUSDT,XAGUSDT,COPPERUSDT,"
        # Energy: WTI crude, natural gas
        "CLUSDT,NATGASUSDT,"
        # Forex: the 4 most-traded USD pairs
        "EURUSDT,GBPUSDT,JPYUSDT,AUDUSDT,"
        # Tokenized stocks: large-cap, liquid, volatile names
        "NVDAUSDT,AAPLUSDT,TSLAUSDT,AMZNUSDT,COINUSDT,"
        # Broad-market indices
        "SPYUSDT,QQQUSDT",
    ).split(",")
    if s.strip()
]
WEEX_SYMBOLS = list(dict.fromkeys(_weex_symbol_list)) if WEEX_ENABLED else []
if WEEX_ENABLED:
    SYMBOLS = list(dict.fromkeys(SYMBOLS + WEEX_SYMBOLS))

MIN_SIGNAL_PROBABILITY = _bounded_float_env("MIN_SIGNAL_PROBABILITY", 70.0, 0.0, 100.0)
MIN_ADX = _bounded_float_env("MIN_ADX", 20.0, 0.0, 100.0)
ATR_SL_MULTIPLIER = _bounded_float_env("ATR_SL_MULTIPLIER", 1.8, 0.1, 20.0)
ATR_TP_MULTIPLIER = _bounded_float_env("ATR_TP_MULTIPLIER", 3.0, 0.1, 50.0)
RISK_PERCENT_PER_TRADE = _bounded_float_env("RISK_PERCENT_PER_TRADE", 1.0, 0.01, 100.0)
SL_WARNING_THRESHOLD = _bounded_float_env("SL_WARNING_THRESHOLD", 0.8, 0.0, 1.0)
TRAILING_TRIGGER_R = _bounded_float_env("TRAILING_TRIGGER_R", 0.5, 0.0, 1.0)
PARTIAL_LOCK_TRIGGER_R = _bounded_float_env("PARTIAL_LOCK_TRIGGER_R", 0.75, 0.0, 1.0)
PARTIAL_LOCK_R = _bounded_float_env("PARTIAL_LOCK_R", 0.5, 0.0, 10.0)
CYCLE_MINUTES = _positive_int_env("CYCLE_MINUTES", 10, minimum=1)
MIN_ATR_PERCENT = _bounded_float_env("MIN_ATR_PERCENT", 0.25, 0.0, 20.0)
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
SMART_CONTEXT_ENABLED = _str_env("SMART_CONTEXT_ENABLED", "1").strip().lower() not in {"0", "false", "no", "off"}
SESSION_VETO_ENABLED = _str_env("SESSION_VETO_ENABLED", "0").strip().lower() in {"1", "true", "yes", "on"}
MIN_SESSION_QUALITY = _bounded_float_env("MIN_SESSION_QUALITY", 0.0, 0.0, 1.0)
ENABLE_DIRECTION_POLICY = _str_env("ENABLE_DIRECTION_POLICY", "0").strip().lower() in {"1", "true", "yes", "on"}
WHALE_BIAS_FILE = _str_env("WHALE_BIAS_FILE", "")
FUNDAMENTAL_FILE = _str_env("FUNDAMENTAL_FILE", "")


def _symbols_env(name):
    return {x.strip().upper() for x in _str_env(name, "").split(",") if x.strip()}

# Per-symbol directional policies. Leave empty unless deliberately validated
# by an out-of-sample study; this prevents accidental one-way restrictions.
BUY_ONLY_SYMBOLS = _symbols_env("BUY_ONLY_SYMBOLS") if ENABLE_DIRECTION_POLICY else set()
SELL_ONLY_SYMBOLS = _symbols_env("SELL_ONLY_SYMBOLS") if ENABLE_DIRECTION_POLICY else set()
