import json
import os
from cryptography.fernet import Fernet, InvalidToken
from config import ENCRYPTION_KEY

try:
    fernet = Fernet(ENCRYPTION_KEY.encode())
except Exception as e:
    raise SystemExit(
        f"❌ ENCRYPTION_KEY نامعتبر است: {e}\n"
        "کلید را با دستور زیر بسازید:\n"
        "python3 -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
    )

STATE_PATH = "state/state.json.enc"
HISTORY_PATH = "data/history.csv"

# Ensure directories exist
os.makedirs("state", exist_ok=True)
os.makedirs("data", exist_ok=True)

DEFAULT_STATE = {
    "trades": [],
    "stats": {"wins": 0, "losses": 0, "streak": 0},
    "circuit_breaker": None,
}


def _with_defaults(state):
    """Fill in any missing keys so older/partial state files never crash the bot."""
    state.setdefault("trades", [])
    state.setdefault("stats", {})
    state["stats"].setdefault("wins", 0)
    state["stats"].setdefault("losses", 0)
    state["stats"].setdefault("streak", 0)
    state.setdefault("circuit_breaker", None)
    return state


def load_state():
    if os.path.exists(STATE_PATH):
        try:
            with open(STATE_PATH, "rb") as f:
                encrypted_data = f.read()
                if encrypted_data:
                    return _with_defaults(json.loads(fernet.decrypt(encrypted_data).decode()))
        except InvalidToken:
            print("⚠️ خطا: فایل state با ENCRYPTION_KEY فعلی قابل رمزگشایی نیست (کلید عوض شده؟). با state پیش‌فرض شروع می‌شود.")
        except Exception as e:
            print(f"⚠️ Error loading state: {e}")
    return _with_defaults(json.loads(json.dumps(DEFAULT_STATE)))


def save_state(state):
    try:
        with open(STATE_PATH, "wb") as f:
            f.write(fernet.encrypt(json.dumps(state).encode()))
        print("✅ State saved successfully.")
    except Exception as e:
        print(f"❌ Error saving state: {e}")
