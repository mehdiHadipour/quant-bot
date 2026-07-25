import requests
from config import TELEGRAM_TOKEN, TELEGRAM_CHAT
from logger import log

TELEGRAM_MAX_LEN = 4096


def send_telegram_alert(message):
    """Send a Telegram message using HTML formatting (main.py's message
    templates rely on intentional <b>...</b> tags throughout — signal
    alerts, trailing-stop notices, the daily report, crash alerts, etc.
    all use them for readability on a phone).

    A v27.2 "hardening" attempt replaced parse_mode=HTML with
    html.escape()-ing the WHOLE message and dropping parse_mode entirely,
    reasoning that dynamic content (e.g. an exception's text) could
    contain a stray <, >, or & and break Telegram's HTML parser. That
    concern is real, but the fix as shipped broke ALL 11+ message types
    in main.py that use <b> for legitimate formatting — every one of them
    would have rendered as literal "&lt;b&gt;...&lt;/b&gt;" text instead
    of bold headers. Fixed here properly: keep parse_mode=HTML for the
    normal case (correct formatting), and if Telegram itself reports a
    parse failure (its own 400 "can't parse entities" response — the
    actual, specific failure mode being worried about), retry ONCE as
    plain text so the alert still gets delivered instead of being lost.
    """
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
                log.info("Telegram alert sent.")
                return
            if resp.status_code == 400 and "parse" in resp.text.lower():
                log.warning(
                    f"Telegram rejected HTML parse ({resp.text[:200]}); "
                    "retrying this message as plain text..."
                )
                plain_resp = requests.post(
                    f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                    json={"chat_id": TELEGRAM_CHAT, "text": message},
                    timeout=10,
                )
                if plain_resp.status_code == 200:
                    log.info("Telegram alert sent as plain text (HTML parse fallback).")
                    return
                log.warning(f"Plain-text fallback also failed: {plain_resp.status_code}")
            else:
                log.warning(f"Telegram API returned {resp.status_code}: {resp.text[:200]}")
        except requests.RequestException as e:
            log.warning(f"Failed to send Telegram alert (attempt {attempt + 1}/3): {e}")
    log.error("Giving up on sending Telegram alert after 3 attempts.")
