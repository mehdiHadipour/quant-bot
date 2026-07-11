import requests
from config import TELEGRAM_TOKEN, TELEGRAM_CHAT

TELEGRAM_MAX_LEN = 4096


def send_telegram_alert(message):
    if not (TELEGRAM_TOKEN and TELEGRAM_CHAT):
        return

    if len(message) > TELEGRAM_MAX_LEN:
        message = message[: TELEGRAM_MAX_LEN - 20] + "\n... (truncated)"

    for attempt in range(3):
        try:
            resp = requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                json={"chat_id": TELEGRAM_CHAT, "text": message, "parse_mode": "HTML"},
                timeout=10,
            )
            if resp.status_code == 200:
                print("✅ Telegram alert sent.")
                return
            print(f"⚠️ Telegram API returned {resp.status_code}: {resp.text[:200]}")
        except requests.RequestException as e:
            print(f"⚠️ Failed to send Telegram alert (attempt {attempt + 1}/3): {e}")
    print("❌ Giving up on sending Telegram alert after 3 attempts.")
