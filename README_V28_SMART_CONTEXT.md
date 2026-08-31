# Quant Bot V28 — Smart Context

This release keeps the existing multi-timeframe strategy and adds a final decision gate:

1. 4H trend + 1D confluence
2. 1H technical score: EMA/MACD/RSI/Stochastic/Volume/Structure/Bollinger/Wick
3. Liquidity Sweep + FVG + rolling VWAP
4. Funding rate (Binance -> Bybit fallback)
5. 15m EMA20 confirmation
6. **Smart Context final gate:**
   - Footprint/Order-flow proxy from taker-buy volume
   - Absorption proxy from wick + opposing flow
   - UTC market session filter
   - Optional Whale bias sidecar
   - Optional Fundamental score sidecar
7. Portfolio risk gate: R/R, daily loss, open risk, same-direction concentration

Important: the footprint is explicitly a proxy because the current Binance kline feed does not contain tick-level bid/ask trades. No synthetic tick data is created. For true historical footprint testing, supply historical tick/aggregate-trade data.

Whale and fundamental data are optional. If absent, they are NEUTRAL, never fabricated.

## Direction restrictions
Use repository Variables only after out-of-sample validation:
- `BUY_ONLY_SYMBOLS=...`
- `SELL_ONLY_SYMBOLS=...`

Do not hard-code restrictions from a small backtest sample.

## Required secrets
`TELEGRAM_TOKEN`, `TELEGRAM_CHAT`, `ENCRYPTION_KEY`.
