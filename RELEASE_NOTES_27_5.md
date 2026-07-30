# Quant Bot 27.5 — Reliability & Direction Safety Release

This release is a hardening pass over the 27.4 review build.

## Direction safety
- Signal direction remains derived from signed market evidence; BUY and SELL probabilities use the same symmetric probability transform.
- New fail-closed price-geometry validation rejects any BUY whose levels are not `SL < Entry < TP`, and any SELL whose levels are not `TP < Entry < SL`.
- New regression tests cover both invalid geometries.
- New-signal analysis uses completed candles; live candles are reserved for open-trade monitoring.

## Trade lifecycle fixes retained
- Intrabar high/low detects TP and SL touches instead of relying only on candle close.
- Conservative same-candle TP+SL handling assumes SL first.
- Original risk is frozen in `initial_risk`, so trailing stops do not corrupt R-multiple accounting.
- Two-stage trailing: breakeven at 0.5R progress, then 0.5R profit lock at 0.75R progress.
- Symbol cooldown, daily loss cap, total open-risk cap, and same-direction concentration guard.

## Reliability fixes retained
- Encrypted state with atomic writes and backup recovery.
- Encrypted trade history with migration from legacy plaintext history.
- Telegram HTML messages with plain-text fallback when Telegram rejects malformed HTML.
- Concurrent market-data fetching with Binance data-api mirror and fallbacks.
- Funding rate is optional/fail-open and never blocks a signal by itself.
- GitHub Actions runs validation, lint, tests, then the trading cycle.

## Important limitation
This bot is a signal/risk-tracking engine, not an exchange order executor. It does not place real Binance/Bybit orders. Its "open trades" are tracked positions/signals in state. No strategy can guarantee profit; the safest release is the one that fails closed when data, geometry, or persistence is invalid.
