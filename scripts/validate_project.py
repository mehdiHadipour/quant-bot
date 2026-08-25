from pathlib import Path
import ast
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
REQUIRED = [
    "main.py", "config.py", "state_manager.py", "trade_monitor.py",
    "risk_engine.py", "backtest.py", "research.py", "requirements.txt",
]
SECRET_PATTERNS = [
    re.compile(r"(?i)(telegram[_-]?token|api[_-]?key|secret[_-]?key)\s*=\s*['\"][^'\"]{12,}['\"]"),
    re.compile(r"(?i)ghp_[A-Za-z0-9]{20,}"),
    re.compile(r"(?i)github_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"(?i)xox[baprs]-[A-Za-z0-9-]{10,}"),
]

errors = []
for name in REQUIRED:
    if not (ROOT / name).exists():
        errors.append(f"missing required file: {name}")

for path in ROOT.rglob("*.py"):
    if any(part in {".git", ".venv", "venv"} for part in path.parts):
        continue
    try:
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except SyntaxError as exc:
        errors.append(f"syntax error in {path}: {exc}")
    text = path.read_text(encoding="utf-8", errors="ignore")
    for pattern in SECRET_PATTERNS:
        if pattern.search(text):
            errors.append(f"possible hard-coded secret in {path}")

req = (ROOT / "requirements.txt").read_text(encoding="utf-8")
if "cryptography" not in req:
    errors.append("cryptography dependency is required for encrypted state")

# Regression guard (added after finding SYMBOLS/SELL_ONLY_SYMBOLS/
# SILENCE_GAP_MULTIPLIER missing or stale in bot.yml on the same day):
# every top-level config.py variable that reads from an environment
# variable (i.e. every real, user-tunable setting) must be wired
# through bot.yml's `vars.X` mechanism, or a live GitHub Actions run
# can silently use a stale/wrong value no one notices. This only checks
# WIRING (the name appears), not whether a hardcoded `|| 'default'`
# fallback value is itself still correct — that still needs a human
# check when a default changes, same as this round's SYMBOLS fix.
_DERIVED_OR_SECRET_CONFIG_VARS = {
    "CRYPTO_SYMBOLS", "COMMODITY_SYMBOLS",  # derived from SYMBOLS, not independently set
    "TELEGRAM_TOKEN", "TELEGRAM_CHAT", "ENCRYPTION_KEY",  # wired via secrets.X, not vars.X
}
config_text = (ROOT / "config.py").read_text(encoding="utf-8")
config_vars = set(re.findall(r"^([A-Z][A-Z_0-9]*)\s*=", config_text, re.MULTILINE))
bot_yml_path = ROOT / ".github" / "workflows" / "bot.yml"
if bot_yml_path.exists():
    bot_yml_text = bot_yml_path.read_text(encoding="utf-8")
    wired_vars = set(re.findall(r"vars\.([A-Z_0-9]+)", bot_yml_text))
    unwired = config_vars - wired_vars - _DERIVED_OR_SECRET_CONFIG_VARS
    if unwired:
        errors.append(
            "config.py vars not wired into .github/workflows/bot.yml (a live run would silently "
            f"ignore any GitHub Variable set for these): {', '.join(sorted(unwired))}"
        )

if errors:
    print("VALIDATION FAILED")
    print("\n".join(f"- {e}" for e in errors))
    sys.exit(1)
print("VALIDATION OK")
