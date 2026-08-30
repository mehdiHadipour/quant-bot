#!/data/data/com.termux/files/usr/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python scripts/validate_project.py
python -m compileall -q .
python -m unittest discover -s tests -p 'test_*.py'
if [ ! -f .env ]; then cp .env.example .env; fi
echo "Setup complete. Edit .env, then run: bash android/run_termux.sh"
