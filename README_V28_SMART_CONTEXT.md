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


## V28.1 Final All-Markets Update
- BTCUSDT and ETHUSDT are always included in the configured symbol universe.
- All symbols are BUY+SELL by default; one-way policies are disabled unless `ENABLE_DIRECTION_POLICY=1`.
- Rollover/low-liquidity hours are no longer a hard blackout by default. `SESSION_VETO_ENABLED=0`.
- ADX and ATR dead-market filters were loosened to 20 and 0.25% respectively; they remain protective rather than removing the filters entirely.
- Live news is disabled automatically in backtest mode to prevent look-ahead bias. Historical fundamental data should be supplied as a timestamped sidecar if it is to affect backtests.
- Validation no longer renames files during a validation run.

## V28.2 — Real Hyperliquid whale confirmation + WEEX TradFi symbols

**Whale bias is now real, not a manual sidecar.** `scripts/update_whale_bias.py`
runs hourly (`.github/workflows/whale_bias.yml`) and reads Hyperliquid's
public, no-auth API directly (the same on-chain data HyperDash itself is
built on — HyperDash has no public API of its own, so this goes to the
source instead of scraping its UI):
- `stats-data.hyperliquid.xyz/Mainnet/leaderboard` for the most profitable
  traders (ranked by realized PnL over the trailing month, min $50k account
  value).
- `api.hyperliquid.xyz/info` (`batchClearinghouseStates`) for those traders'
  currently open positions.

Positions are aggregated per coin, weighted by notional size (a $5M
position outweighs a $5K one), into `whale_bias.json`
(`{"BTC": {"bias": "BUY", "confidence": 0.82, ...}, ...}`). `main.py` points
`WHALE_BIAS_FILE` at this file, so `smart_context.py`'s existing whale-bias
gate (unchanged) now confirms/vetoes signals against real top-trader
positioning instead of a manually-maintained JSON. Deliberately **not**
wired into `backtest.yml` — using today's live whale positions to score a
year-old backtest candle would be look-ahead bias, the same reason
`NEWS_ENABLED=0` in backtests above.

**WEEX TradFi tokenized products** (`weex_data_engine.py`) add gold, silver,
oil/gas, forex, tokenized US stocks, and indices to the tradable universe,
fetched from WEEX's public spot kline API (`api-spot.weex.com`) instead of
Binance. This uses WEEX's **spot** klines (not its separate perpetual-futures
contract API) as price input, and these are tokenized/synthetic USDT-settled
instruments tracking the underlying price, not the underlying commodity,
currency, or equity itself.

Default `WEEX_SYMBOLS` (one representative per asset, to avoid firing several
near-identical correlated signals for the same underlying move):
`XAUUSDT, XAGUSDT, COPPERUSDT` (metals), `CLUSDT, NATGASUSDT` (energy),
`EURUSDT, GBPUSDT, JPYUSDT, AUDUSDT` (forex), `NVDAUSDT, AAPLUSDT, TSLAUSDT,
AMZNUSDT, COINUSDT` (stocks), `SPYUSDT, QQQUSDT` (indices).

Full confirmed WEEX TradFi list (from the user's own app screenshots,
2026-08-27) if you want to override `WEEX_SYMBOLS` with more:
- Commodities: `NGUSDT`, `NATGASUSDT`, `CLUSDT` (WTI oil), the Brent-oil one
  shown as "OIL(BZ)USDT" in-app (ticker inferred as `BZUSDT`, unverified)
- Metals: `XAUUSDT`, `XAGUSDT`* (silver, inferred), `COPPERUSDT`, `XCUUSDT`
  (a second copper listing), `SLVUSDT` (iShares Silver ETF), `PAXGUSDT` /
  `XAUTUSDT` (two more tokenized-gold variants), `XPDUSDT`* (palladium,
  inferred), `XPTUSDT`* (platinum, inferred), `XALUSDT`* (aluminium, inferred)
- Forex: `EURUSDT`, `GBPUSDT`, `JPYUSDT`, `AUDUSDT`, `CADUSDT`, `CHFUSDT`,
  `BRLUSDT`
- Stocks: `NVDAUSDT`, `AAPLUSDT`, `TSLAUSDT`, `AMZNUSDT`, `COINUSDT`,
  `MSTRUSDT`, `ORCLUSDT`, `PLTRUSDT`, `FUTUUSDT`, `RDDTUSDT`
- Indices: `SPYUSDT`, `QQQUSDT`, `TQQQUSDT` (3x leveraged), `SOXXUSDT`,
  `SOXLUSDT` (3x leveraged), `XLEUSDT`, `EWJUSDT`, `EWYUSDT`, `EWTUSDT`,
  `IEFAUSDT`
- Pre-IPO (illiquid/highly volatile -- not recommended for an automated
  technical-analysis bot, included here only for completeness):
  `ANTHROPICUSDT`, `OPENAIUSDT`, `ENFLAMEUSDT`, `MOONSHOTUSDT`

\* = ticker inferred from WEEX's own consistent in-app naming pattern
("COMMONNAME(TICKER)USDT" -> the API symbol is TICKER+USDT, confirmed
directly for PAXG and XAUT), not independently verified against the live
API. If wrong, that single symbol just fails to fetch and is skipped
(logged as a WARNING) -- it cannot break fetching for any other symbol.

Adding many more of these at once meaningfully increases every 5-minute
cycle's request count (`fetch_all_klines` fetches 4 timeframes per symbol).
The `bot.yml` job timeout was raised from 8 to 12 minutes and the
kline-fetch thread pool from 12 to 24 workers to give headroom for the
larger default symbol set; widen further if you add most/all of the list
above. `WEEX_ENABLED=0` disables all WEEX symbols entirely.


