import os
import sys
from dotenv import load_dotenv
from logger import log

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT = os.getenv("TELEGRAM_CHAT")
ENCRYPTION_KEY = os.getenv("ENCRYPTION_KEY")

_missing = [
    name for name, value in [
        ("TELEGRAM_TOKEN", TELEGRAM_TOKEN),
        ("TELEGRAM_CHAT", TELEGRAM_CHAT),
        ("ENCRYPTION_KEY", ENCRYPTION_KEY),
    ] if not value
]

if _missing:
    print(
        "❌ خطا: متغیرهای محیطی زیر تنظیم نشده‌اند: "
        + ", ".join(_missing)
        + "\nاین مقادیر باید در GitHub Secrets (Settings > Secrets and variables > Actions) "
        "تنظیم شوند و هرگز نباید داخل کد نوشته شوند.\n"
        "⚠️ توجه: اگر ENCRYPTION_KEY نامعتبر باشد، ربات هرگز نباید خودش یک کلید تصادفی "
        "جایگزین بسازد؛ چون در آن صورت state رمزنگاری‌شدهٔ اجرای قبلی برای همیشه غیرقابل "
        "بازیابی می‌شود. به همین دلیل این‌جا صریحاً متوقف می‌شویم تا مشکل واقعی دیده و رفع شود.",
        file=sys.stderr,
    )
    sys.exit(1)


def _float_env(name, default):
    """Read a numeric setting from a GitHub Secret/Variable, falling back to
    a safe default and warning (not crashing) on a bad value."""
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return float(raw)
    except ValueError:
        log.warning(f"مقدار {name}='{raw}' نامعتبر بود؛ مقدار پیش‌فرض {default} استفاده شد.")
        return default


def _str_env(name, default):
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return raw


# نمادهای معاملاتی که ربات هر چرخه تحلیل می‌کند.
# برای شخصی‌سازی، یک Secret/Variable با نام SYMBOLS بسازید (مثال: "BTCUSDT,ETHUSDT").
# نمادهای معاملاتی که ربات هر چرخه تحلیل می‌کند.
# برای شخصی‌سازی، یک Secret/Variable با نام SYMBOLS بسازید (مثال: "BTCUSDT,ETHUSDT").
#
# v25.9 NOTE: HYPEUSDT was added in v25.7 and removed here. Binance's
# GLOBAL platform (binance.com) only lists HYPE as a FUTURES contract —
# its spot market (HYPE/USDT) exists only on the separate Binance.US
# exchange, a different API entirely. fetch_klines() in data_engine.py
# only ever queries binance.com's public SPOT mirrors
# (data-api.binance.vision, api.binance.com, api1/api3), so every single
# request for HYPEUSDT failed on every mirror, every cycle (400 = symbol
# doesn't exist there, or 451 = geo-blocked, depending on the mirror) —
# harmless (fails open, doesn't affect other symbols) but pure log noise
# forever. Any future symbol addition should first be confirmed to have
# a binance.com SPOT listing, not just a futures one — they're not the
# same thing for every coin.
SYMBOLS = [
    s.strip()
    for s in _str_env(
        "SYMBOLS",
        "BTCUSDT,ETHUSDT,BNBUSDT,SOLUSDT,XRPUSDT,ADAUSDT,DOGEUSDT,AVAXUSDT,LINKUSDT,DOTUSDT,"
        "ZECUSDT,SUIUSDT,TONUSDT,NEARUSDT",
    ).split(",")
    if s.strip()
]

# === تنظیمات v19.0 Ultra Confluence ===
# حداقل درصد احتمال (0-100) که یک سیگنال باید داشته باشد تا "قوی" در نظر گرفته و ارسال شود.
MIN_SIGNAL_PROBABILITY = _float_env("MIN_SIGNAL_PROBABILITY", 70.0)

# حداقل مقدار ADX (قدرت روند). زیر این مقدار بازار "رنج/بدون روند" در نظر گرفته می‌شود و
# هیچ سیگنالی صادر نمی‌شود، حتی اگر بقیهٔ شرایط برقرار باشند.
MIN_ADX = _float_env("MIN_ADX", 25.0)

# ضرایب ATR برای محاسبهٔ حد ضرر (SL) و حد سود (TP).
ATR_SL_MULTIPLIER = _float_env("ATR_SL_MULTIPLIER", 1.8)
ATR_TP_MULTIPLIER = _float_env("ATR_TP_MULTIPLIER", 3.0)

# درصد پیشنهادی از سرمایه که در هر معامله به ریسک گذاشته شود (فقط برای نمایش راهنما در
# پیام تلگرام استفاده می‌شود؛ ربات خودش مبلغی معامله نمی‌کند).
RISK_PERCENT_PER_TRADE = _float_env("RISK_PERCENT_PER_TRADE", 1.0)

# وقتی قیمت این‌قدر از فاصلهٔ کل بین ورود و SL را طی کرده باشد (مثلاً 0.8 یعنی ۸۰٪ راه
# تا حد ضرر)، یک هشدار یک‌باره در تلگرام ارسال می‌شود تا قبل از خوردن SL مطلع شوید.
SL_WARNING_THRESHOLD = _float_env("SL_WARNING_THRESHOLD", 0.8)

# وقتی قیمت این‌قدر از فاصلهٔ کل بین ورود و TP را طی کرده باشد (مثلاً 0.5 یعنی نیمهٔ راه
# تا هدف سود)، SL به‌صورت خودکار به نقطهٔ ورود منتقل می‌شود تا معامله دیگر ریسکی نداشته
# باشد، حتی اگر قیمت کاملاً برگردد و به SL اصلی برسد.
TRAILING_TRIGGER_R = _float_env("TRAILING_TRIGGER_R", 0.5)

# مدت هر چرخهٔ اجرا (به دقیقه) — باید با مقدار cron در .github/workflows/bot.yml هماهنگ
# باشد. برای محاسبهٔ درست مدت واقعی Cooldown استفاده می‌شود.
CYCLE_MINUTES = int(_float_env("CYCLE_MINUTES", 5))

# How many missed cycles' worth of silence before the "haven't run in a
# while" watchdog alerts (see check_silence_gap in main.py). Some slack
# above 1x is needed because GitHub's cron scheduler is best-effort and
# routinely delays a few minutes under load — this should only fire for
# a genuine multi-cycle gap (workflow paused/disabled, repeated crashes),
# not normal scheduling jitter.
SILENCE_GAP_MULTIPLIER = _float_env("SILENCE_GAP_MULTIPLIER", 6.0)

# بعد از اینکه یک معامله با ضرر (LOSS) بسته شد، ربات به‌مدت این تعداد چرخه دیگر سیگنال
# جدیدی روی همان نماد باز نمی‌کند. برای غیرفعال‌کردن، مقدار 0 بگذارید.
SYMBOL_COOLDOWN_CYCLES = int(_float_env("SYMBOL_COOLDOWN_CYCLES", 6))

# === تنظیمات v25.0 ===
# حداکثر تعداد معاملات باز هم‌زمان (روی همهٔ ۱۰ نماد با هم). چون خیلی از این نمادها
# (مثلاً BTC/ETH/BNB) هم‌بسته حرکت می‌کنند، بدون این سقف ممکن است ربات چند سیگنال
# هم‌جهت و هم‌بسته را هم‌زمان باز کند که عملاً یک ریسک بزرگ را چند بار تکرار کرده، نه
# واقعاً متنوع‌سازی. برای غیرفعال‌کردن این محدودیت، مقدار 0 بگذارید.
MAX_CONCURRENT_TRADES = int(_float_env("MAX_CONCURRENT_TRADES", 4))
