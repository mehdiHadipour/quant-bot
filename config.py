import os
from dotenv import load_dotenv
from cryptography.fernet import Fernet

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT = os.getenv("TELEGRAM_CHAT")
ENCRYPTION_KEY = os.getenv("ENCRYPTION_KEY")

# اگر کلید موجود نبود یا نامعتبر بود، خودکار یک کلید جدید و استاندارد بساز
try:
    if not ENCRYPTION_KEY:
        ENCRYPTION_KEY = Fernet.generate_key().decode()
        print("⚠️ ENCRYPTION_KEY پیدا نشد. یک کلید جدید ساخته شد.")
    else:
        # چک کردن اینکه آیا کلید وارد شده فرمت درستی دارد یا نه
        Fernet(ENCRYPTION_KEY.encode())
except Exception:
    ENCRYPTION_KEY = Fernet.generate_key().decode()
    print("⚠️ ENCRYPTION_KEY نامعتبر بود. یک کلید جدید و استاندارد ساخته شد.")

if not TELEGRAM_TOKEN or not TELEGRAM_CHAT:
    print("⚠️ هشدار: تنظیمات تلگرام کامل نیست. پیام‌ها ارسال نمی‌شوند.")

# لیست ارزهای قابل تحلیل
SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
