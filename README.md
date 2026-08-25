# Quant Bot V27.12 — Hybrid AdaptiveTrend Final

Production package based on V27.11 with the strongest research component from V31 integrated as the default signal regime.

## What is integrated
- V31 4H EMA(6/18) AdaptiveTrend direction.
- 30-day 4H realized-volatility regime check.
- Volatility-target weight calculation (20% annualized target, 1.0x asset cap).
- V27 production risk controls, encrypted state/history, Telegram alerts, cooldowns, circuit breakers, two-stage trailing stop, diagnostics, GitHub Actions and Android companion.
- Legacy V27 scoring strategy remains available with `ADAPTIVE_TREND_ENABLED=false`.

## Important execution note
The V31 research backtest is a portfolio research model. The live bot uses the same AdaptiveTrend direction/regime logic to generate actionable BUY/SELL alerts, while V27's ATR SL/TP, risk gates and trailing protection remain the execution layer.

## Supplied-data backtest
Dataset: BTCUSDT, ETHUSDT, SOLUSDT 15m/1h/4h/1d supplied by the user.
Base cost: 0.16% round-trip.

- Full return: 1063.14%
- CAGR: 500.43%
- Max drawdown: -14.72%
- Annualized Sharpe: 4.28
- Chronological 30% OOS return: 90.71%
- OOS CAGR: 381.67%

Stress:
- 0.30% round-trip: +623.37%, max DD -16.86%, OOS +64.10%
- 0.50% round-trip: +266.64%, max DD -20.04%, OOS +32.35%

These are research backtest figures, not a guarantee of live profit. The supplied V27 trade-history backtest itself was negative (-24.50R over 229 trades), so the final package deliberately does not claim that V27's old entry engine was profitable.

## GitHub
Use `.github/workflows/bot.yml` for scheduled execution and `backtest.yml` for manual backtests.

Required GitHub Secrets:
- `TELEGRAM_TOKEN`
- `TELEGRAM_CHAT`
- `ENCRYPTION_KEY`

The Android companion is under `android-companion/` and can be built by the included Android workflow.

## V27.13 Multi-Market upgrade
The bot now supports WEEX commodity/TradFi market data for XAUUSDT (gold), XAGUSDT (silver), CLUSDT (crude oil) and NATGASUSDT (natural gas), while retaining the V27 execution/risk stack and V31 AdaptiveTrend overlay. WEEX documents public historical contract K-lines for 15m/1h/4h/1d. Commodity funding-rate scoring is disabled because funding is not a crypto-market input.

Important: the user's supplied backtest ZIP contained only BTC/ETH/SOL data, so the included report does **not** pretend to have backtested commodities. Run `scripts/fetch_weex_historical.py` followed by `multi_market_backtest.py` to obtain a genuine multi-market result.

## Robustness/risk hardening (post-review additions)

Found and fixed during an independent code review:
- **Dead config wired in**: `MAX_OPEN_PER_MARKET_GROUP`/`DIVERSIFICATION_ENABLED` were defined in `config.py` for the V27.13 multi-market upgrade and already passed through in `bot.yml`, but nothing ever read them — a portfolio could end up fully concentrated in one market group (e.g. several simultaneous commodity trades) with no cap enforcing the intended diversification. `risk_engine.can_open_trade()` now enforces it via the new `market_group_open_count()` helper, wired into both `main.py` and `scripts/run_backtest.py`.

New, additive (all off/no-op unless the underlying data supports them; nothing here changes default trading behavior):
- **Third crypto data source (OKX)**: `data_engine.fetch_klines()` now falls back to OKX's public klines endpoint only after every Binance mirror in `BASE_URLS` has failed — covers a whole-exchange-level Binance outage/block, not just a single-mirror hiccup. `taker_buy_volume` is left at 0 for OKX-sourced candles (OKX's public endpoint doesn't expose that split), which the existing order-flow scoring already treats as neutral.
- **Soft performance throttle**: `risk_engine.performance_throttle_multiplier()` compares the last 20 CLOSED trades' realized expectancy against a conservative baseline (`main.BASELINE_EXPECTANCY_R`) and, if live performance has drifted well below it, adds a suggested position-size reduction to the Telegram signal message. This is informational only — separate from, and does not replace, the existing hard circuit breaker (3 consecutive losses). It exists because a slow bleed of small losses can underperform the backtest for a long stretch without ever tripping 3-in-a-row.
- **Walk-forward fold + Monte Carlo robustness report**: `research.py` gained `monte_carlo_bootstrap()` (reshuffles closed trades' R-multiples to show a distribution of possible drawdown/ruin outcomes, not just the one historical sequence) and `walk_forward_fold_metrics()` (summarizes each walk-forward fold's out-of-sample window separately, to catch a strategy whose backtest profit came from one regime rather than a durable edge). Run against any `scripts/run_backtest.py` output:
  ```
  python scripts/run_backtest.py --symbols BNBUSDT,SOLUSDT,DOGEUSDT,AVAXUSDT,LINKUSDT,DOTUSDT,ZECUSDT,NEARUSDT
  python scripts/validate_robustness.py --input backtest_data/backtest_results.csv
  ```

**Deliberately NOT implemented: automatic order execution on a real exchange.** The bot still only sends Telegram alerts; it does not place live orders. Wiring real execution in requires the user's own exchange API keys, exchange-specific order/margin handling, and extensive testing against that exchange's live API — none of which can be done or verified in this environment. Getting this wrong risks real, immediate capital loss (not just a missed alert), so it is intentionally out of scope here rather than shipped untested.
