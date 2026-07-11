import os
from dotenv import load_dotenv
from cryptography.fernet import Fernet

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT = os.getenv("TELEGRAM_CHAT")
ENCRYPTION_KEY = os.getenv("ENCRYPTION_KEY")

if not ENCRYPTION_KEY:
    ENCRYPTION_KEY = Fernet.generate_key().decode()
    print("⚠️ کلید رمزنگاری (ENCRYPTION_KEY) پیدا نشد. یک کلید جدید ساخته شد.")

if not TELEGRAM_TOKEN or not TELEGRAM_CHAT:
    print("⚠️ هشدار: تنظیمات تلگرام کامل نیست. پیام‌ها ارسال نمی‌شوند.")
