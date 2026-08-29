from pathlib import Path
import ast, re, sys
ROOT=Path(__file__).resolve().parents[1]
REQUIRED=["main.py","config.py","state_manager.py","trade_monitor.py","risk_engine.py","backtest.py","data_engine.py","indicators.py","smart_context.py","news_provider.py","requirements.txt"]
errors=[]
for name in REQUIRED:
    if not (ROOT/name).exists(): errors.append(f"missing required file: {name}")
for path in ROOT.rglob("*.py"):
    if any(part in {".git",".venv","venv"} for part in path.parts): continue
    try: ast.parse(path.read_text(encoding="utf-8"),filename=str(path))
    except SyntaxError as exc: errors.append(f"syntax error in {path}: {exc}")
    text=path.read_text(encoding="utf-8",errors="ignore")
    for pat in [r"(?i)(telegram[_-]?token|api[_-]?key|secret[_-]?key)\s*=\s*['\"][^'\"]{12,}['\"]",r"ghp_[A-Za-z0-9]{20,}",r"github_pat_[A-Za-z0-9_]{20,}"]:
        if re.search(pat,text): errors.append(f"possible hard-coded secret in {path}")
req=(ROOT/"requirements.txt").read_text(encoding="utf-8")
if "cryptography" not in req: errors.append("cryptography dependency required")

# Guard against the state-persistence bug: bot.yml declares
# `permissions: contents: write` (signalling intent to commit something
# back to the repo) and runs main.py, which relies on state_manager.py's
# state/state.json.enc (open trades, stats, cooldowns) and
# data/history.csv.enc surviving between scheduled runs. Each GitHub
# Actions run is a fresh ephemeral VM -- anything main.py writes locally
# is lost at the end of the job unless a step explicitly commits it back.
# Without that step, every 5-minute cycle silently starts from a blank
# state: trades get announced via Telegram but are never tracked to a
# win/loss, so daily performance reports stay stuck at 0/0 forever, with
# no error or crash to signal why.
bot_workflow = ROOT / ".github" / "workflows" / "bot.yml"
if bot_workflow.exists():
    wf_text = bot_workflow.read_text(encoding="utf-8")
    if "contents: write" in wf_text and "python main.py" in wf_text:
        if not re.search(r"git\s+(add|commit|push).*state", wf_text, re.DOTALL) and \
           not re.search(r"git add[^\n]*state", wf_text):
            errors.append(
                "bot.yml runs main.py and declares contents:write but has no step "
                "that commits state/ back to the repo -- trades would never persist "
                "between scheduled runs (daily reports would stay stuck at 0/0)"
            )

if errors:
    print("VALIDATION FAILED")
    print("\n".join("- "+e for e in errors)); sys.exit(1)
print("VALIDATION OK")
