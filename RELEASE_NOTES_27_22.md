# V27.22 — Per-Symbol Direction Policy

Based entirely on the user's own real (demo-account) trading results, not
an independent backtest finding.

## Symbol list restructured

Removed entirely (no longer traded): `BTCUSDT`, `ETHUSDT`, `XRPUSDT`,
`ADAUSDT`, `SUIUSDT`, `TONUSDT`. Restricted to SELL-only:  `BNBUSDT`,
`SOLUSDT`, `AVAXUSDT`, `LINKUSDT`, `NEARUSDT`. Fully bidirectional (no
change): `DOGEUSDT`, `DOTUSDT`, `ZECUSDT`.

**Important limitation, stated plainly**: of these 14 symbols, real
historical data has only ever been available in this project for
`BTCUSDT`/`ETHUSDT`/`SOLUSDT`. `ZECUSDT`, `DOGEUSDT`, `DOTUSDT`,
`BNBUSDT`, `AVAXUSDT`, `LINKUSDT`, `NEARUSDT` have never been backtested
here — this change trusts the user's real, observed trade outcomes for
those, not something independently verified. To actually validate them:
```
python scripts/fetch_historical_klines.py --symbols ZECUSDT,DOGEUSDT,DOTUSDT,BNBUSDT,AVAXUSDT,LINKUSDT,NEARUSDT --days 700
python scripts/run_backtest.py --symbols ZECUSDT,DOGEUSDT,DOTUSDT,BNBUSDT,AVAXUSDT,LINKUSDT,NEARUSDT
```

## New feature: per-symbol direction restriction

Added `config.SELL_ONLY_SYMBOLS` (default: the 5 symbols above) and
`config.direction_allowed(symbol, direction)` — a single, auditable
choke point checked identically in `main.py`'s live loop (right after
`analyze_market()` returns a direction) and `scripts/run_backtest.py`'s
simulation loop, so backtest and live behavior stay matched per this
repo's existing convention. A BUY signal for a SELL-only symbol is
treated as no-signal-this-cycle (logged, not sent), not blocked
elsewhere in the pipeline — SELL signals for those symbols, and both
directions for unrestricted symbols, are entirely unaffected.

## SOL sell-only: validated with real data — a genuinely interesting
   result

The only symbol in this policy with real historical data available. Full
2-year backtest with the restriction applied: 454 trades, expectancy
-0.102 — WORSE than SOL's unrestricted 2-year baseline (812 trades,
-0.079). Breaking the baseline down by direction explains why: over the
full 2 years, BUY (-0.064) actually outperformed SELL (-0.093) for SOL —
the opposite of what the sell-only restriction assumes.

But splitting the same baseline data into "last 90 days" vs "everything
before that" resolves the apparent contradiction: in the last 90 days
(closer to when the user's real trades happened), BUY was far worse
(-0.257) than SELL (-0.109) — consistent with the user's actual
experience, even though it's the opposite of the 2-year average. This
reads as a real, recent shift in which direction has an edge for SOL,
not a contradiction to explain away. Recommendation: keep the
restriction, since it matches the currently-observed pattern — but note
the recent-window sample is small (82 trades) and market regimes can
shift again, so this isn't a permanent, closed question.

## Testing

153 tests, all passing. New `tests/test_config.py` (7 tests) for
`direction_allowed`/`SELL_ONLY_SYMBOLS`: SELL-only blocks BUY but never
SELL, unrestricted symbols allow both, the default sets match this
round's exact requested policy, and removed symbols aren't in the
default `SYMBOLS` list.
