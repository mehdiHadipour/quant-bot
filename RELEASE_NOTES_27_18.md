# V27.18 — Time-Stop (and Four More Rejected Hypotheses)

## Five hypotheses tested on real data this round; four rejected

Following the established discipline (validate against real trade data
before implementing anything), five different "why do trades fail"
hypotheses were tested against the real 1733-trade full-period backtest
(and, for the last one, a controlled 260-day re-simulation):

| Hypothesis | Test | Result |
|---|---|---|
| Entry-timing / crossover freshness | correlation with r_multiple | **-0.012 — rejected** |
| Order-flow (CVD) agreement with direction | grouped comparison | **~0 difference — rejected** |
| RSI extremity at entry | correlation with r_multiple | **0.009 — rejected** |
| Distance from EMA6 at entry | correlation with r_multiple | **0.003 — rejected** |
| Wider SL/TP (2.5xATR, same 1:1 ratio) | real re-simulation, same 260-day window | **worse expectancy (-0.129 vs -0.102) — rejected** |
| **Trade duration / "stalled" trades** | correlation + grouped comparison | **real signal — implemented, see below** |

Also corrected a mistake from earlier in this round: an initial "6.9% win
rate" figure for the full 2-year run was based on the `result` column
(WIN only = full TP hit), not true financial outcome. Recomputed correctly
using `r_multiple > 0`: true win rate is 41.7%, breakeven 25.7%, true loss
32.6% — a much healthier picture, and consistent with the walk-forward
tool's fold-level numbers (which already used the correct `r_multiple`
based definition, which is why they looked so different from the initial,
wrong headline figure).

## What DID validate: time-stop for stalled trades

Trades still under 0.3R progress toward TP after 8 hours went on to
average a real **-0.33R** final outcome (32.5% eventual win rate); trades
that HAD reached that much progress by then averaged **+0.42R** (64.4% win
rate) — by far the cleanest, largest split found among everything tested
this round or the last. Interpreted as: fast resolution (either direction)
reflects market conviction; trades that drift sideways for hours tend to
keep drifting into a loss rather than recover.

**Implemented**: `trade_monitor.check_time_stop()` — closes a trade at
current market price if it has been open longer than `TIME_STOP_HOURS`
(default 8) without reaching `TIME_STOP_MIN_PROGRESS_R` (default 0.3)
progress toward TP. Wired into both `main.py` (live) and
`scripts/run_backtest.py` (so backtest and live behavior stay matched, per
this repo's existing convention), checked AFTER the organic SL/TP check
each cycle so a genuine TP/SL hit always takes priority. Disabled (no-op)
when `TIME_STOP_HOURS <= 0`. A time-stop exit gets `result: "TIME_STOP"`
(distinct from WIN/LOSS) and folds into the circuit-breaker's win/loss
streak by the SIGN of its actual r_multiple, since it doesn't have a
natural SL/TP binary.

**Re-validated with a real backtest re-run** (not just the correlation
check) on the same controlled 260-day window used for the earlier SL/TP
experiment:

| | Without time-stop | With time-stop |
|---|---|---|
| Trades | 337 | 464 |
| Win rate | 40.7% | 41.8% |
| Expectancy | -0.102 | **-0.085 (real improvement)** |
| Profit Factor | 0.68 | 0.69 |
| Net R | -34.48 | -39.59 |
| ETHUSDT expectancy alone | -0.010 | **+0.006 (turned positive)** |

**Honest summary**: per-trade quality genuinely improved (expectancy,
profit factor), consistent with the correlation that motivated this. But
because closing trades faster frees up concurrent-trade slots sooner, MORE
trades happened in the same window (464 vs 337, +38%) — enough that total
portfolio R was slightly worse despite each trade being somewhat better on
average. This is a real, validated, but partial improvement, not a fix.

## Order Flow / Footprint charts (user's separate question, Instagram
   screenshots)

Assessed and NOT pursued for now: genuine footprint/order-flow analysis
needs tick-level trade data (not the candle-aggregate `taker_buy_volume`
this bot already has), which Binance/WEEX's kline REST APIs don't provide
— it would need a new data source (e.g. `aggTrades`) and a fundamentally
different, much heavier data pipeline, poorly suited to a cron-driven
GitHub Actions bot versus the real-time desktop platform (NinjaTrader)
shown in the screenshots. Given the core signal is still being validated
incrementally, adding a much larger infrastructure commitment before that
is resolved isn't a good trade. The CVD hypothesis tested above (built
from data already available, no new infrastructure) is the
closest cheap approximation of this idea, and it didn't hold up either.

## Testing

140 tests, all passing (7 new: `TestTimeStop` covering disabled/enabled,
too-young, stalled-vs-progressed, BUY/SELL, missing-`initial_risk`
fail-open, and wrong-symbol cases; plus a streak/cooldown test for
`TIME_STOP`'s sign-based WIN/LOSS folding in `update_circuit_breaker`).
