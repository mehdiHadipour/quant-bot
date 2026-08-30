import json
import os
import shutil
from cryptography.fernet import Fernet, InvalidToken
import config
from logger import log

def _get_fernet():
    if not config.ENCRYPTION_KEY:
        raise RuntimeError("ENCRYPTION_KEY is required for state encryption")
    try:
        return Fernet(config.ENCRYPTION_KEY.encode())
    except Exception as exc:
        raise RuntimeError(f"Invalid ENCRYPTION_KEY: {exc}") from exc


STATE_PATH = "state/state.json.enc"
BACKUP_PATH = "state/state.json.enc.bak"
HISTORY_PATH = "data/history.csv"

# Ensure directories exist
os.makedirs("state", exist_ok=True)
os.makedirs("data", exist_ok=True)

STATE_SCHEMA_VERSION = 2

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
    "schema_version": STATE_SCHEMA_VERSION,
}


def _with_defaults(state):
    """Fill in any missing keys so older/partial state files never crash the bot."""
    state.setdefault("schema_version", STATE_SCHEMA_VERSION)
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
    state.setdefault("gate_skip_counts", {})
    state.setdefault("gate_skip_alerted", {})

    # v25.6 migration: trades opened before this fix don't have
    # "initial_risk" stored. Backfill it once, here, from whatever "sl"
    # currently holds. For a trade not yet trailed to breakeven, sl still
    # IS the original stop — so this recovers the true value. For a trade
    # already trailed (sl == entry already), this is the same fallback
    # number the old buggy code was already using — no worse than before,
    # just no longer silently wrong for every trade going forward. Only
    # runs once per trade: after this, "initial_risk" is present and this
    # loop skips it.
    for trade in state.get("trades", []):
        if trade.get("status") == "open" and "initial_risk" not in trade:
            trade["initial_risk"] = abs(trade.get("entry", 0) - trade.get("sl", 0))
        # v25.12: trades opened before the second trailing stage shipped
        # don't have this flag; default it so check_trailing_stop's `.get()`
        # checks behave identically to a freshly-opened trade.
        if trade.get("status") == "open":
            trade.setdefault("sl_partial_lock_done", False)

    state["schema_version"] = STATE_SCHEMA_VERSION
    return state


def _decrypt_file(path):
    """Read and decrypt a state file. Raises on any failure so the caller
    can decide how to react (try the backup, or fall back to defaults)."""
    with open(path, "rb") as f:
        encrypted_data = f.read()
    if not encrypted_data:
        raise ValueError("empty file")
    return json.loads(_get_fernet().decrypt(encrypted_data).decode())


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
    """Persist encrypted state atomically and fail closed on errors.

    A silent persistence failure can cause the next scheduled cycle to operate
    on stale state, which is unsafe for trade tracking and portfolio risk.
    """
    tmp_path = STATE_PATH + ".tmp"
    try:
        fernet = _get_fernet()
        state = _with_defaults(state)
        new_bytes = fernet.encrypt(
            json.dumps(state, ensure_ascii=False, sort_keys=True).encode()
        )

        with open(tmp_path, "wb") as f:
            f.write(new_bytes)
            f.flush()
            os.fsync(f.fileno())

        if os.path.exists(STATE_PATH):
            try:
                shutil.copyfile(STATE_PATH, BACKUP_PATH)
            except Exception as e:
                log.warning(f"گرفتن نسخهٔ backup از state ناموفق بود: {e}")

        os.replace(tmp_path, STATE_PATH)
        log.info("State saved successfully.")
    except Exception:
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except OSError:
            pass
        log.exception("Error saving state; failing closed so the next cycle cannot run on stale state.")
        raise

