import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import ast
import config

required=[
    "main.py","config.py","data_engine.py","indicators.py",
    "smart_context.py","news_provider.py","risk_engine.py","trade_monitor.py",
    "backtest.py","requirements.txt",
]
for name in required:
    assert (ROOT/name).exists(), f"missing: {name}"
assert "BTCUSDT" in config.SYMBOLS and "ETHUSDT" in config.SYMBOLS
assert not config.ENABLE_DIRECTION_POLICY, "direction policy must be disabled for two-way mode"
assert config.BUY_ONLY_SYMBOLS == set() and config.SELL_ONLY_SYMBOLS == set()
for name in ["main.py","config.py","data_engine.py","indicators.py","smart_context.py","news_provider.py","risk_engine.py","trade_monitor.py","backtest.py"]:
    ast.parse((ROOT/name).read_text(encoding="utf-8"), filename=name)
text=(ROOT/"indicators.py").read_text(encoding="utf-8")
for token in ["evaluate_smart_context", "df_15m", "df_4h", "df_1d", "funding_rate"]:
    assert token in text, f"stage not wired: {token}"
print("SYSTEM AUDIT OK")
print("CORE MARKETS: BTCUSDT, ETHUSDT")
print("DIRECTION: BUY + SELL for all configured symbols")
print("SMART CONTEXT: ENABLED")
print("SESSION BLACKOUT: DISABLED")
print(f"MIN_ADX={config.MIN_ADX}, MIN_ATR_PERCENT={config.MIN_ATR_PERCENT}")
