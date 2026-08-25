# V27.19 — Look-Ahead Audit, WEEX Research, Graduated Time-Stop

Three things requested this round, executed in order.

## 1. Look-ahead bias audit: clean

Searched for the classic patterns (`shift(-N)`, centered rolling windows,
backward-fill) across `indicators.py`, `backtest.py`,
`scripts/run_backtest.py`, `data_engine.py`, `adaptive_strategy.py` —
none found. Manually re-verified the core no-lookahead guarantee
(`slice_as_of` keeps only candles with `close_time <= as_of`),
`detect_rsi_divergence` (only compares the current row against the prior
rows in its own window, never a future one), and `check_open_trades`'
SL/TP resolution (only uses the current candle's high/low/close, and
conservatively assumes SL wins when both TP and SL fall in the same
candle — biased AGAINST the strategy looking good, the opposite of
look-ahead). **No look-ahead bias found** — the last two weeks of
backtest results are methodologically sound.

One related, non-bug methodological note: entry price is the same
candle's close as the signal (a zero-latency fill assumption), consistent
between backtest and live, so it doesn't inflate backtest results
relative to live specifically — but both are mildly optimistic relative
to a real exchange, partially offset by the existing `fee_r`/`slippage_r`
backtest parameters.

## 2. WEEX metals/oil/gas/indices research

Researched via web search (this environment has no direct API access to
verify against WEEX live). Confirmed: WEEX's TradFi section offers gold,
silver, crude oil, natural gas (already integrated since V27.13/14) PLUS
tokenized stocks and global indices (NAS100, HK50, and by extension
likely US30/SPX500). Exact ticker strings for the index/stock candidates
could **not** be verified from this environment — WEEX's own how-to
examples use bare tickers ("NAS100", "TSLA") which may not match this
codebase's existing "XAUUSDT"-style suffix convention.

Added as clearly-flagged, NOT-yet-verified candidates: `NAS100USDT`,
`US30USDT`, `SPX500USDT`, `HK50USDT` in
`data_engine.WEEX_COMMODITY_SYMBOLS` and a commented-out extended
`SYMBOLS` line in `.env.example`. The live default `SYMBOLS` list is
UNCHANGED (still the original 14 crypto + 4 verified commodities) —
these new candidates require the user's own verification (in an
environment with internet access) before enabling them for real.

## 3. Graduated time-stop (was: single threshold)

V27.18 added `check_time_stop` with one checkpoint (8h, 0.3R). Researched
established open-source bot frameworks (Freqtrade — most popular by far,
53k+ stars; Jesse; Hummingbot) for comparison. Freqtrade's
`NostalgiaForInfinity` (a widely-used, actively community-vetted
strategy) uses a graduated time-based ROI table — the minimum acceptable
profit to hold a trade rises as it ages — the same core idea as V27.18's
single threshold, just generalized into a decay schedule.

Before implementing, an earlier (4h) checkpoint candidate was tested the
same way V27.18's 8h one was: trades under 0.10R progress at 4h averaged
a real -0.35R final outcome vs +0.29R for trades that had reached it —
independently validated, not just extrapolated. `TIME_STOP_SCHEDULE`
replaces `TIME_STOP_HOURS`/`TIME_STOP_MIN_PROGRESS_R`: a comma-separated
`hours:min_progress_r` list (default `4:0.10,8:0.30`), parsed and sorted
ascending. At evaluation time, a trade is judged against the LATEST
checkpoint whose hour threshold it has already passed — so a 10-hour-old
trade is judged by the 8h checkpoint (more demanding), not the 4h one it
already cleared. Deliberately stops at 8h: a 32-64h duration bucket in
the same underlying data swung back to a small POSITIVE average outcome,
so extending the decay further isn't supported by anything actually
tested — don't add later checkpoints without validating them the same
way first.

Re-validated with a real backtest re-run on the same controlled 260-day
window used for V27.18's validation:

| | No time-stop | V27.18 (8h/0.3R only) | V27.19 (4h+8h graduated) |
|---|---|---|---|
| Trades | 337 | 464 | 524 |
| Win rate | 40.7% | 41.8% | 34.9% |
| Expectancy | -0.102 | -0.085 | **-0.070 (best so far)** |
| Profit Factor | 0.68 | 0.69 | 0.68 |
| Net R | -34.48 | -39.59 | -36.65 |

Per-trade expectancy keeps improving with each real, validated change —
now roughly 31% better than the no-time-stop baseline. Win rate dropped
(the earlier 4h checkpoint cuts some trades before they'd have resolved
into a small eventual win), and net portfolio R is still not positive,
for the same reason as V27.18: closing trades faster frees up
concurrent-trade slots sooner, so more trades happen in the same window.
Real, measured, incremental progress — not a fix.

Config/workflow changes: `TIME_STOP_HOURS`/`TIME_STOP_MIN_PROGRESS_R`
fully replaced by `TIME_STOP_SCHEDULE` in `config.py`, `.env.example`,
and `.github/workflows/bot.yml`.

## Testing

141 tests, all passing. `TestTimeStop` rewritten for the schedule-based
API (checkpoint precedence, empty-schedule disable, etc.). One
pre-existing test (`test_max_daily_loss_r_blocks_new_entries_across_
portfolio_same_day`) started failing after the time-stop change — not a
bug in either feature: its synthetic fixture has a long flat pre-crash
period that the new 4h checkpoint correctly time-stopped before the
crash it was designed to test ever happened. Fixed by disabling
`trade_monitor.TIME_STOP_SCHEDULE` for `PortfolioGatesTests` (that test
class isolates other gates and was never meant to also exercise
time-stop timing).
