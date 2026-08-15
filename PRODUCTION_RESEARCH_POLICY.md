# Quant Bot v27.2 — Production Research Policy

## What this release improves

This is a reliability and research-hardening release. It does not promise
profitability.

### Fail-closed state persistence
If encrypted state cannot be saved, the workflow now fails instead of silently
continuing with stale state. This reduces the risk of duplicate trade tracking
and incorrect portfolio-risk calculations on the next cycle.

### Robust Telegram alerts
Alerts are sent as plain text rather than parsed HTML, so dynamic market data
or error messages cannot accidentally break Telegram formatting.

### Research metrics
`research.py` adds:
- net R after configurable fee and slippage assumptions
- expectancy
- win rate
- Profit Factor
- Max Drawdown
- chronological walk-forward train/test windows

## Recommended validation order

1. Historical backtest.
2. Include realistic fees, slippage, and missed fills.
3. Keep a completely untouched out-of-sample period.
4. Run walk-forward tests.
5. Paper trade across multiple market regimes.
6. Compare paper results with backtest expectations.
7. Only then consider a separately isolated execution adapter.

No code change can guarantee that a strategy will be profitable.

## Public GitHub warning

The current workflow persists `data/history.csv` in the repository. If the
repository is public, this can expose trading history and strategy behavior.
For serious deployment, prefer a private repository or replace CSV persistence
with encrypted/object storage.

The encrypted state file is protected by the encryption key, but repository
metadata and history should still be treated as sensitive.

## Android

The Android companion is a monitoring client. It does not hold exchange keys
or Telegram secrets and should not become a trading execution client without
a dedicated authenticated backend.
