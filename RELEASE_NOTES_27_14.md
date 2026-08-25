# V27.14 — Robustness Review Follow-up

## Critical fix (found via user's GitHub Actions CI lint output)

**`analyze_market()`'s default strategy path crashed on every real call.** The
`ADAPTIVE_TREND_ENABLED` branch in `indicators.py` (the DEFAULT strategy —
`ADAPTIVE_TREND_ENABLED` defaults to `true` in `config.py`, and the README
describes it as the primary regime engine) referenced `buy_ratio`,
`liquidity_sweep`, and `divergence` in its returned dict, but those three
variables were only computed later, in the legacy-scoring code path further
down the function — code that a successful AdaptiveTrend return skips
entirely. Every call that reached that return statement raised
`NameError: name 'buy_ratio' is not defined` (or `liquidity_sweep`/
`divergence`, whichever ruff's F821 check happened to flag first).

Ruff's `F821 Undefined name` output (from the user's own `quality.yml` CI
job) caught this correctly. The existing test suite's smoke tests
(`test_does_not_raise_on_a_strong_uptrend` etc.) missed it because they used
perfectly deterministic, noise-free linear price trends — realistic enough
to pass every earlier check, but with realized volatility low enough to
trip an earlier `return None` (`rv_4h < ADAPTIVE_MIN_RV`) before ever
reaching the buggy return statement. Real market data always has noise, so
in practice this meant the bot could never produce a single AdaptiveTrend
signal under default settings — every cycle would have crashed instead.

**Fix**: moved the computation of `divergence`, `prev_high`/`prev_low`,
`liquidity_sweep`, and `buy_ratio` earlier in `analyze_market()`, before the
`ADAPTIVE_TREND_ENABLED` branch, so both the AdaptiveTrend and legacy
return paths can use them; removed the now-duplicate computations further
down. Added `tests/test_indicators.py::TestAdaptiveTrendPathDoesNotCrash`,
which deliberately uses seeded random noise (not a clean deterministic
trend) specifically so the AdaptiveTrend success path actually executes —
that's the only way a test can catch this class of bug.

Also fixed, from the same CI lint output: 4 unused-import errors (F401:
stray `pathlib.Path`/`numpy` imports in `adaptive_backtest_engine.py`,
`scripts/run_adaptive_backtest.py`, `multi_market_backtest.py`) and 2
unused-local-variable errors (F841: an unused `sig` in two backtest
scripts' loops, and an unused `reason` in one of this repo's own existing
tests) — all 7 errors ruff reported, now resolved.

## Robustness review follow-up (previous round)

Changes made after an independent code review of V27.13, at the user's request
to "make the bot stronger." The review found the codebase already covers most
of the standard signal-quality ground (multi-timeframe confluence on
15m/1H/4H/1D, ADX/regime filtering, a dedicated volatility-regime AdaptiveTrend
mode, liquidity-sweep/FVG/order-flow/funding-rate scoring, encrypted state,
circuit breakers, two-stage trailing stop). Effort this round focused on real
gaps found during review rather than re-doing things that already existed.

## Fixed
- `MAX_OPEN_PER_MARKET_GROUP` / `DIVERSIFICATION_ENABLED` (added in V27.13 for
  the crypto/commodity multi-market split, and already passed through in
  `bot.yml`) were never actually read anywhere — a real gap, not by design.
  `risk_engine.can_open_trade()` now enforces a per-market-group open-trade
  cap via the new `market_group_open_count()` helper, wired into both
  `main.py` and `scripts/run_backtest.py` (so backtest and live behavior stay
  matched, per this repo's existing convention).

## Added
- `data_engine.fetch_okx_klines()` — a third, independent crypto data source
  used only after every Binance mirror has failed, for whole-exchange-level
  outages (not just a single geo-blocked mirror, which the existing 5-mirror
  Binance fallback already handled).
- `risk_engine.performance_throttle_multiplier()` — a soft, informational
  throttle comparing the last 20 closed trades' realized expectancy against a
  conservative baseline; surfaces a suggested position-size reduction in the
  Telegram signal message (`main.build_risk_tip()`) when live performance has
  drifted well below what the backtest/research promised. This is separate
  from, and does not replace, the existing hard circuit breaker.
- `research.monte_carlo_bootstrap()` and `research.walk_forward_fold_metrics()`
  plus `scripts/validate_robustness.py` — reshuffles a backtest's closed
  trades to show a distribution of possible drawdown/ruin outcomes (not just
  the one historical sequence), and reports each walk-forward fold's
  out-of-sample metrics separately to catch a strategy whose apparent edge
  came from a single market regime rather than being durable.

## Explicitly not done
Automatic order execution on a real exchange. This bot still only sends
Telegram alerts. Real execution needs the user's own exchange API keys,
exchange-specific order/margin handling, and live-API testing that cannot be
done or verified in this environment — the risk of shipping that untested is
real capital loss, not just a missed alert.

## Testing
26 new unit tests added across `tests/test_risk_and_backtest.py` (market-group
diversification cap + performance throttle), `tests/test_research.py`
(Monte Carlo + walk-forward fold metrics), `tests/test_data_engine.py` (OKX
fallback, new file), and `tests/test_main.py` (risk-tip throttle note,
recent-realized-R helper). Full suite: 126 tests, all passing against a
faithful offline reimplementation of the `ta` library's specific indicator
methods this codebase calls (this sandboxed review environment has no
internet access to install the real package) — re-verify with the real `ta`
package in CI/GitHub Actions, which `.github/workflows/bot.yml` already does
on every run via `pip install -r requirements.txt`.
