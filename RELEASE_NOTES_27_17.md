# V27.17 — TP Recalibration (and a Rejected Hypothesis)

## Answering "which earlier version had a higher win rate?"

Comparing all three real backtest runs supplied so far (all before this
round's changes):

| Run | Trades | Win rate | Mean R/trade | Sum R |
|---|---|---|---|---|
| 1st (no ADX filter at all) | 2550 | **13.69%** (highest) | -0.1107 | -282.3 |
| 2nd (1H ADX — later found buggy) | 1789 | 13.30% | **-0.0966** (least-bad) | -172.8 |
| 3rd (4H ADX — the correct fix) | 1461 | 12.87% (lowest) | -0.1165 | -170.2 |

The very first run (before any ADX filter existed) had the highest raw win
rate. The second run had the best per-trade expectancy. All three were net
losing overall — "higher win rate" alone doesn't mean "better," which is
part of why this round moved to a different lever entirely (see below)
instead of tuning the ADX/MTF filters further.

## Hypothesis tested and REJECTED: entry-timing ("crossover freshness")

Manually inspecting the 10 trades that went wrong immediately (0% MFE
progress) suggested a pattern: entries seemed to land right at the peak/
trough of a short burst that had just caused the EMA(6)/EMA(18) crossover,
immediately followed by a reversal — a classic "lagging indicator" symptom.

Before implementing anything, this was tested against the FULL 1461-trade
dataset (not just the 10 examples) by computing, for every trade, how many
4H bars old the crossover was at entry time, and correlating that against
`r_multiple`. Result: correlation coefficient **-0.012** (essentially
zero), and bucketed win rates showed no usable pattern (fresh crossovers:
14.1% win rate; 10-19 bars old: 10.5%; 20+ bars old: 13.3% — not
monotonic, no signal). **The hypothesis did not hold up under real data
and nothing was implemented for it.** The 10-trade sample that motivated
it was too small and not representative — this is precisely the kind of
mistake the earlier ADX-timeframe fix already burned two rounds
correcting for (inspection-based hypotheses need validation against the
full dataset before being coded, not just a plausible story from a
handful of examples).

## Real, data-driven change: TP was very likely set too far

Using the maximum-favorable-excursion (MFE) data already computed for
every trade (peak progress toward the OLD 3.0xATR target before eventual
exit), an approximate re-simulation tested what total return several
smaller TP distances would have produced on the SAME historical trades:

| TP as multiple of ATR | Implied win rate | Mean R/trade | Sum R |
|---|---|---|---|
| 0.9 (fraction 0.3) | 68.1% | +0.022 | +31.5 |
| 1.2 (fraction 0.4) | 62.2% | +0.037 | +54.0 |
| 1.5 (fraction 0.5) | 57.0% | +0.044 | **+64.3 (best)** |
| 1.8 (fraction 0.6) | 46.4% | +0.032 | +47.0 |
| 2.1 (fraction 0.7) | 38.4% | +0.012 | +17.5 |
| 2.4 (fraction 0.8) | 31.2% | -0.002 | -2.5 |
| 3.0 (fraction 1.0, current) | 19.1% | -0.043 | -63.0 |

**Caveat, important**: this is an approximation, not a true re-simulation
— it assumes a trade whose MFE reached a smaller target would have exited
there (reasonable, since price moves monotonically toward its peak before
reversing in the vast majority of cases) but does not re-run
`simulate_trade()`'s exact same-candle conservative-ambiguity rule against
the new, closer TP. Since SL and a reduced TP sit closer together, more
candles will plausibly touch both levels in the same candle than before,
which the real simulator resolves conservatively (SL wins) — something
this approximation does not fully capture. The approximation likely
OVERSTATES the benefit somewhat, especially at the more extreme (very
close) TP distances. The general direction — the current 3.0xATR target
is very likely too far for how this signal actually behaves — is visible
directly in the underlying MFE distribution, not just this one estimate.

**Change made**: `ATR_TP_MULTIPLIER` 3.0 -> **1.8** (a 1:1 reward:risk
with the unchanged 1.8xATR stop-loss — a deliberately moderate choice,
not the approximation's peak at 1.5, to stay away from the region where
the approximation's known bias is largest). `MIN_REWARD_RISK` 1.5 -> 1.0
correspondingly (a 1.5 minimum would reject every trade at a 1:1 TP/SL
ratio). Both are `.env`-overridable as before; `.env.example` updated to
match.

**This has NOT been validated by a real backtest re-run** — only by the
approximation above. Re-run `scripts/run_backtest.py` with these new
defaults and compare against the table above before trusting this with
real capital; given the approximation's known bias, expect the real
number to likely be less dramatic than +64R, though probably still an
improvement over the current -170R given how large and consistent the
underlying MFE pattern is.

## Testing

132 tests, all passing — this round's config change didn't require test
updates (existing tests pass `min_reward_risk` explicitly rather than
relying on the changed config default).
