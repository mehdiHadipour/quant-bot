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
if errors:
    print("VALIDATION FAILED")
    print("\n".join("- "+e for e in errors)); sys.exit(1)
print("VALIDATION OK")
