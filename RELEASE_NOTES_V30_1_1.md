# Quant Bot V30.1.1 — Stability / Install / Signal Audit Fix

## Critical fixes
1. Fixed `main.py` live signal path: a Smart Context block referenced `result` and `msg` before they were created. This could make every signal-processing cycle fail before sending a signal.
2. Fixed `scripts/run_backtest.py` so it works from GitHub Actions and from any working directory by adding the repository root to `sys.path`.
3. Fixed research/backtest higher-timeframe resampling to use completed bars only (`closed='left', label='right'`) and removed a BPR look-ahead caused by `shift(-1)`.
4. Added the configured `NEWS_BLOCK_MINUTES` to the live decision path: recent high-impact RSS headlines can now activate a new-entry blackout.
5. Removed the external `ta` package dependency and vendored a minimal local compatibility implementation containing only the indicators used by this project. This reduces Android/GitHub installation fragility.

## Verified
- `python scripts/validate_project.py` → VALIDATION OK
- Python compileall → OK
- Unit tests → 8/8 PASS
- `python scripts/run_backtest.py` → SUCCESS
- Main module import → SUCCESS
- Android Termux setup/run scripts included

## Important data limitations
- Footprint is a taker-buy-volume proxy unless tick/order-flow data is supplied.
- Hyper-Liquidity is a volume/range proxy unless real order-book depth is supplied.
- Live news uses public Google News RSS; historical backtests remain neutral unless a timestamped sidecar is supplied.
- This is not a native APK. Android execution is supported through Termux; GitHub Actions remains the recommended scheduled runner.

## V30.2.0 — Fibonacci Confluence
- Added leakage-safe Fibonacci retracement scoring to live signal generation.
- Added Fibonacci to deterministic backtest output and signal records.
- Selected compact research setting: 50 completed bars; preferred 50%-78.6% pullback zone; OTE 61.8%-78.6%.
- Backtest on supplied 14-symbol dataset: 97 trades, 30 wins, 67 losses, 30.93% win rate, -7.00R, PF 0.896, MaxDD 24R.
