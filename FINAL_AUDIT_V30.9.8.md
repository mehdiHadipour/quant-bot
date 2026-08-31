# Quant Bot V30.9.8 — Final Engineering Audit

## Scope
This release is a hardened research candidate based on V30.9.7. The goal is to make the manual configuration authoritative for the strategy/backtest defaults, remove a known workflow contradiction, and keep Live/Backtest on the same signal configuration source.

## Checks performed
- `python -m pytest -q` — 19 passed.
- `python -m unittest discover -s tests -p 'test_*.py'` — passed.
- `python scripts/validate_project.py` — VALIDATION OK.
- `python -m compileall -q .` — passed.
- ZIP integrity test — passed.

## Important fixes
1. Fibonacci OTE is no longer forced by the TradFi workflow when manual configuration disables the gate.
2. Backtest Fibonacci requirement now follows `manual_settings.json` unless explicitly overridden by `REQUIRE_FIB_OTE`.
3. Backtest session bonus/thresholds are read from the same manual session configuration rather than hard-coded values.
4. Backtest MACD parameters, ATR period, sweep/MSS lookbacks, displacement threshold, VP lookback/bins, TP R-range, minimum RR and maximum holding bars are configurable.
5. Backtest startup no longer relies on `c` being defined only when `V30_SELECTED_CONFIG.json` exists.
6. `STRICT_SYMBOLS` and negative sessions can be controlled from `manual_settings.json`.

## Selected research baseline
- Fibonacci lookback: 72
- OTE: 0.618–0.85
- Signal threshold: 65
- Displacement minimum: 0.85
- ATR period: 14
- VP lookback: 60
- VP bins: 40
- Minimum backtest RR: 1.8
- TP range: 2R–4R
- Maximum hold: 97 bars
- Fibonacci hard gate: OFF
- Regime hard gate: OFF
- Session filter: ON

## Internal backtest on the data bundled with this release
Trades: 12
Wins: 8
Losses: 4
Win rate: 66.67%
Net R: +12.00R
Average R: +1.000R
Profit Factor: 4.000
Max Drawdown: 1.00R

This is NOT a two-year validation and is NOT proof of live profitability. The bundled data are a research sample. The two-year GitHub workflow should be run after installation, and the resulting OOS/Walk-Forward report should be used before any live deployment.

## Configuration rule
`manual_settings.json` is the intended human-editable configuration. Environment variables remain available as explicit deployment overrides. Risk limits must remain independent of signal-score settings.
