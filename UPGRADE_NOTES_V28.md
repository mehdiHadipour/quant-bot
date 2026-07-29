# Quant Bot v28.0 — Stability & Signal Quality Upgrade

## What changed

- Rebuilt directional scoring so every score component is signed. Positive evidence can no longer accidentally weaken SELL signals.
- BUY/SELL confidence now comes from one symmetric score-to-confidence function. It is explicitly a confidence score, not a calibrated probability.
- Added strict 4H + 1D regime agreement before entry.
- Strengthened 15m confirmation: EMA20 position + EMA20 slope + 15m MACD direction.
- Added DMI (+DI/-DI) to measure directional pressure.
- Added ATR sanity gates to reject zero/invalid, extremely quiet, and extreme-volatility setups.
- Added a minimum absolute signal score to reject weak sign-flips around zero.
- Added exhaustion protection for extreme Bollinger extensions.
- RSI divergence against the proposed direction now blocks the entry instead of merely warning.
- Kept FVG, liquidity sweep, VWAP, taker-buy pressure, funding rate, stochastic, Bollinger and volume as supporting evidence rather than allowing any one indicator to dominate.
- Reduced the default same-direction open-trade cap from 3 to 2 to reduce correlated crypto exposure.
- Fixed the reported Ruff issue by removing unused live timeframe assignments.
- Backtest now applies the daily realized-loss guard per symbol and reports BUY/SELL counts.
- Telegram alerts now show confidence and the 4H/1D regime.
- Existing encrypted state, atomic save, backup recovery, trailing-stop, partial-profit-lock, Telegram fallback, and fail-closed risk controls are retained.

## Important

This release is a **research/stability upgrade, not a promise of profitability**. The previous backtest was materially negative (PF 0.59, expectancy -0.185R, max drawdown 55.19R), so the correct next step is to run a fresh out-of-sample backtest and walk-forward validation before any live use.

Recommended validation:
1. Run 180–365 days on BTC/ETH/SOL plus the full symbol universe.
2. Compare BUY and SELL separately.
3. Compare each symbol separately.
4. Test bull, bear and sideways regimes.
5. Run a strict out-of-sample period not used for tuning.
6. Do not increase risk until expectancy is positive after fees/slippage and remains positive out-of-sample.

## GitHub Actions variables

New optional repository variables:
- `MIN_ATR_PERCENT` (default 0.35)
- `MAX_ATR_PERCENT` (default 8.0)
- `MIN_SIGNAL_SCORE` (default 28.0)

If these variables are absent, the defaults above are used automatically.
