# Quant Bot v28.0.2 — Targeted Strategy/Backtest Fixes

## Changed files
- `indicators.py`
- `config.py`

## Critical fixes
1. **FVG signal bug fixed**
   - `fvg` was calculated inside `_directional_components()` but was not returned.
   - `analyze_market()` then referenced `fvg` directly, which could raise `NameError` when a signal reached the final payload.
   - FVG is now returned as `d["fvg"]` and exposed safely.

2. **4H trend bias made symmetric**
   - The old 4H score used `close > EMA200`, while the 1D regime gate used `EMA50 > EMA200`.
   - This mismatch can keep the 4H side bearish during recovery and contribute to a persistent SELL bias.
   - 4H scoring now uses the same EMA50-vs-EMA200 regime definition as the regime gate.

3. **Opposite score corrected**
   - `opposite_score` was always negative (`-abs(score)`), even for a SELL signal.
   - It now correctly mirrors the signed score (`-score`).

4. **Signal quality defaults tightened**
   - Default `MIN_SIGNAL_PROBABILITY`: 70 → 72
   - Default `MIN_SIGNAL_SCORE`: 28 → 32
   - These are defaults only; GitHub Actions Variables can override them.
   - The goal is fewer marginal entries, not a guarantee of profitability.

## Important
After replacing these files, run the backtest again on the same historical period. Do not judge the strategy from one run. Compare:
- Expectancy > 0
- Profit Factor > 1
- BUY/SELL distribution
- Results per symbol
- Max Drawdown
- Number of trades

The changes are deliberately targeted and do not claim guaranteed profit.
