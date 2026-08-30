# اجرای Quant Bot روی Android با Termux

این پروژه یک ربات Python است؛ APK بومی نیست. برای اجرای مستقیم روی گوشی Android از Termux استفاده کنید. GitHub Actions برای اجرای زمان‌بندی‌شده مناسب است و گوشی می‌تواند برای مدیریت/مانیتورینگ استفاده شود.

## نصب
1. Termux را از منبع معتبر نصب کنید.
2. داخل Termux:
```bash
pkg update -y
pkg install -y python git openssl
```
3. پروژه را Clone کنید و وارد پوشه شوید.
4. اجرا:
```bash
bash android/setup_termux.sh
```
5. `.env` را از `.env.example` بسازید و `TELEGRAM_TOKEN`، `TELEGRAM_CHAT` و `ENCRYPTION_KEY` را تنظیم کنید.
6. برای اجرای دستی:
```bash
bash android/run_termux.sh
```

> اجرای 24/7 روی Android به محدودیت‌های باتری/Doze بستگی دارد. برای اجرای زمان‌بندی‌شده پایدار، GitHub Actions گزینه اصلی پروژه است.
