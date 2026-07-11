import os
import sys
from dotenv import load_dotenv

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
        "تنظیم شوند و هرگز نباید داخل کد نوشته شوند.",
        file=sys.stderr,
    )
    sys.exit(1)

# Trading symbols the bot analyzes each cycle. Override with SYMBOLS env var,
# comma-separated, e.g. "BTCUSDT,ETHUSDT"
SYMBOLS = [s.strip() for s in os.getenv("SYMBOLS", "BTCUSDT,ETHUSDT,SOLUSDT").split(",") if s.strip()]
