# Quant Bot v28.1

- Tightened signal confidence default: 75%.
- Tightened minimum directional score: 32.
- Added MIN_DI_EDGE=5 to reject weak DI separation.
- Added 1H EMA20 slope/price + DI alignment gate.
- Increased default TP from 3.0 ATR to 3.6 ATR while keeping SL at 1.8 ATR (about 2R target).
- Kept fail-closed BUY/SELL price geometry validation.
- Cleaned bytecode/cache files from release ZIP.

Important: these changes are designed to improve trade selectivity and reward/risk, not to guarantee profitability. Validate with out-of-sample and walk-forward tests before live trading.
