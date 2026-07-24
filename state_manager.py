import json
import os
import shutil
from cryptography.fernet import Fernet, InvalidToken
from config import ENCRYPTION_KEY
from logger import log

try:
    fernet = Fernet(ENCRYPTION_KEY.encode())
except Exception as e:
    raise SystemExit(
        f"❌ ENCRYPTION_KEY نامعتبر است: {e}\n"
        "کلید را با دستور زیر بسازید:\n"
        "python3 -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
    )

STATE_PATH = "state/state.json.enc"
BACKUP_PATH = "state/state.json.enc.bak"
HISTORY_PATH = "data/history.csv"

# Ensure directories exist
os.makedirs("state", exist_ok=True)
os.makedirs("data", exist_ok=True)

DEFAULT_STATE = {
    "trades": [],
    "stats": {
        "wins": 0,
        "losses": 0,
        "streak": 0,
        "equity_r": 0.0,
        "peak_equity_r": 0.0,
        "max_drawdown_r": 0.0,
        "gross_profit_r": 0.0,
        "gross_loss_r": 0.0,
    },
    "circuit_breaker": None,
}


def _with_defaults(state):
    """Fill in any missing keys so older/partial state files never crash the bot."""
    state.setdefault("trades", [])
    state.setdefault("stats", {})
    state["stats"].setdefault("wins", 0)
    state["stats"].setdefault("losses", 0)
    state["stats"].setdefault("streak", 0)
    state["stats"].setdefault("equity_r", 0.0)
    state["stats"].setdefault("peak_equity_r", 0.0)
    state["stats"].setdefault("max_drawdown_r", 0.0)
    state["stats"].setdefault("gross_profit_r", 0.0)
    state["stats"].setdefault("gross_loss_r", 0.0)
    state.setdefault("circuit_breaker", None)
    state.setdefault("last_report_date", None)
    state.setdefault("symbol_cooldowns", {})
    state.setdefault("consecutive_fetch_failures", 0)
    state.setdefault("fetch_failure_alert_sent", False)
    state.setdefault("last_cycle_completed_at", None)
    return state


def _decrypt_file(path):
    """Read and decrypt a state file. Raises on any failure so the caller
    can decide how to react (try the backup, or fall back to defaults)."""
    with open(path, "rb") as f:
        encrypted_data = f.read()
    if not encrypted_data:
        raise ValueError("empty file")
    return json.loads(fernet.decrypt(encrypted_data).decode())


def load_state():
    if os.path.exists(STATE_PATH):
        try:
            state = _with_defaults(_decrypt_file(STATE_PATH))
            log.info("state موجود با موفقیت بارگذاری شد.")
            return state
        except InvalidToken:
            log.warning("فایل state با ENCRYPTION_KEY فعلی قابل رمزگشایی نیست (کلید عوض شده؟).")
        except Exception as e:
            log.warning(f"فایل state اصلی خراب/غیرقابل‌خواندن بود: {e}")

        # Primary file exists but couldn't be used — try the backup before
        # giving up and starting from a blank state.
        if os.path.exists(BACKUP_PATH):
            try:
                state = _with_defaults(_decrypt_file(BACKUP_PATH))
                log.warning("state از نسخهٔ backup (state.json.enc.bak) بازیابی شد؛ ممکن است چند دقیقه قدیمی‌تر باشد.")
                return state
            except Exception as e:
                log.error(f"نسخهٔ backup هم قابل استفاده نبود: {e}")
    else:
        log.info("هیچ فایل state موجودی پیدا نشد؛ با state پیش‌فرض تازه شروع می‌شود (طبیعی است در اولین اجرا).")

    return _with_defaults(json.loads(json.dumps(DEFAULT_STATE)))


def save_state(state):
    try:
        new_bytes = fernet.encrypt(json.dumps(state).encode())

        # Keep the previous known-good file as a backup before overwriting,
        # so a corrupted/interrupted write never loses everything.
        if os.path.exists(STATE_PATH):
            try:
                shutil.copyfile(STATE_PATH, BACKUP_PATH)
            except Exception as e:
                log.warning(f"گرفتن نسخهٔ backup از state ناموفق بود (ادامه می‌دهیم): {e}")

        # Write-then-rename instead of writing STATE_PATH directly: if the
        # GitHub Actions job is killed (timeout, OOM, cancel) mid-write, a
        # direct write can leave a half-written, corrupted primary file —
        # which then also gets copied over the backup on the *next* run
        # before anyone notices, corrupting both copies. Writing to a temp
        # file first and using os.replace() (atomic on POSIX) means
        # STATE_PATH is only ever fully-old or fully-new, never partial.
        tmp_path = STATE_PATH + ".tmp"
        with open(tmp_path, "wb") as f:
            f.write(new_bytes)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, STATE_PATH)
        log.info("State saved successfully.")
    except Exception as e:
        log.error(f"Error saving state: {e}")
