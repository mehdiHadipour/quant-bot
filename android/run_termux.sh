#!/data/data/com.termux/files/usr/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
source .venv/bin/activate
python main.py
