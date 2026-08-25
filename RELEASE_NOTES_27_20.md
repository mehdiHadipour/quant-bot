# V27.20 — Third Profit-Lock Tier (Near-TP)

## Context

Responding to a large feature-request list ("V28 Final Engine") and a
question about a live Claude-in-the-loop approval step. Both addressed
directly in chat (most requested items already exist in the codebase;
"Claude approves every signal live" isn't architecturally possible — this
chat has no persistent, always-on presence between the bot's runs; a
rule-based Signal Review Engine with APPROVE/REJECT/WATCH is the
buildable version of that idea and remains a candidate for a future
round). This release covers the one concrete, validated improvement that
came out of it.

## What was found

A pattern repeated across every backtest reviewed this project: roughly
30% of non-WIN trades reach 70%+ of the way to TP before reversing. The
existing two-stage trailing stop (breakeven at 50% progress, partial-lock
of 0.5R at 75%) already captures much of this as a small locked profit —
but trades that got even closer (90%+) before reversing were still only
banking that same flat 0.5R, leaving real, measured value on the table.

## What changed

Added a third, tighter trailing-stop tier in `trade_monitor.check_trailing_stop()`:
at `NEAR_TP_LOCK_TRIGGER_R` (default 0.90 — 90% of the way to TP), SL
moves to lock in `NEAR_TP_LOCK_R` (default 0.70) instead of stage 2's
0.5R. Checked tightest-stage-first, same principle as the existing two
stages, so a candle that jumps straight past multiple thresholds locks
the most it earned directly. New config vars wired into `config.py`,
`.env.example`, and `.github/workflows/bot.yml`.

## Validation — the most rigorous of this project so far

Learning from two earlier rounds (the TP recalibration and the time-stop
schedule) where a single, specific recent window looked like a clear win
but the full 2-year dataset told a different story, this change was
tested on **two independent, non-overlapping ~340-day eras** (the
earliest and latest thirds of the full dataset, together ~94% of it) —
not the same window relied on before.

| | Early era (no tier 3) | Early era (with tier 3) | Late era (no tier 3) | Late era (with tier 3) |
|---|---|---|---|---|
| Trades | 906 | 902 | 898 | 882 |
| Expectancy | -0.152 | **-0.136** | -0.091 | **-0.065** |

Both eras improved, in the same direction, independently — 10.5% and
28.6% relative improvement respectively. Combined (1784 trades, ~94% of
the full 2-year dataset): expectancy -0.1215 -> **-0.1008**, a 17%
relative improvement. This is the first change in this project validated
as a real, consistent effect across two independent periods rather than
looking good on one window and failing to generalize.

**Still net-negative overall** — this is a genuine, measured improvement,
not a fix. The full result is in `RELEASE_NOTES` history; nothing here
should be read as "the bot is now profitable."

## Requested breakdown table (on the new-tier combined-era backtest, 1784 trades)

| Category | Count | % |
|---|---|---|
| Reached full TP | 38 | 2.1% |
| Wrong-direction from the start | 22 | 1.3% (of non-WIN) |
| 0-20% of the way to TP | 449 | 25.7% |
| 20-50% of the way to TP | 448 | 25.7% |
| 50-70% of the way to TP | 316 | 18.1% |
| 70%+ of the way to TP (not reached) | 511 | 29.3% |

Note: the "reached full TP" figure looks low in isolation, but (as shown
in earlier rounds' analysis of the same pattern) most of the "70%+"
bucket is now this update's own doing — trades that get that close and
reverse are increasingly banked at 0.7R real profit via the new tier
rather than continuing to look for the full TP.

## Testing

146 tests, all passing. 5 new tests for the third tier (`TestTrailingStop`):
basic trigger, single-candle jump-past-all-stages, SELL direction,
progressive three-stage trail across cycles, and a no-further-action
guard once fully trailed. One pre-existing test's fixture (a big single
candle at 80% progress) was adjusted since it now lands below the new,
tighter 90% tier rather than being ambiguous with it.
