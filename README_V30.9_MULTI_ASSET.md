# Quant Bot V30.9.1 — Audited WEEX Multi-Asset Research-First

This release expands the bot architecture for WEEX TradFi perpetuals while keeping new markets **out of live trading until they pass an out-of-sample approval test**.

## Supported research classes
- Metals
- Energy / commodities
- Stocks
- ETFs
- Indices
- Forex when WEEX V3 actually exposes an API-tradable contract

## Safety rule
`TRADFI_LIVE_APPROVAL_REQUIRED=1` is the default. A TradFi symbol is live only if:
1. WEEX `apiTradingSymbols` says it is API-tradable.
2. WEEX `exchangeInfo` identifies it as `TRADIFI_PERPETUAL`.
3. Historical data exists.
4. The same strategy gates pass, including mandatory Fibonacci OTE.
5. The OOS promotion policy approves the symbol.

## Direction-specific protection
After enough closed trades, BUY and SELL are evaluated independently:
- NORMAL — acceptable expectancy
- STRICT — weak/negative expectancy; higher confluence required
- BLOCK — materially negative expectancy; direction disabled

A profitable direction can remain active even if the opposite direction is weak.

## Telegram diagnostics
Two non-spam alert layers are included:
- **Signal Gate Sentinel:** repeated rejection by the same gate for the same symbol.
- **Performance Sentinel:** statistically meaningful negative expectancy for a symbol, direction or session.

Every live trade stores a diagnostic snapshot containing session, Fibonacci OTE, HLI, order-flow state and Volume Profile context.

## Research workflow
Run GitHub Actions → **Quant Bot - WEEX TradFi Research Backtest**.
It downloads WEEX V3 historical klines and runs the existing leakage-safe backtest. Then `scripts/promote_tradfi.py` writes the approval policy. The workflow does not place orders.

## Fibonacci hard gate
Every live/backtest entry is required to be inside the directional 61.8%–78.6% Fibonacci OTE zone. The default completed-bar lookback is 72 candles. The gate is enforced in both `indicators.py` and `ict_full_backtest.py`.

## Runtime state persistence
GitHub Actions persists the encrypted runtime state and encrypted trade history back to the repository after each bot cycle. This is required because a hosted runner is ephemeral. The encryption key remains only in GitHub Secrets.

## Important data limitation
True footprint/Level-2 is not fabricated. The current order-flow layer uses WEEX taker-buy volume as a proxy. True tick/LOB footprint requires historical trade/Level-2 data.
