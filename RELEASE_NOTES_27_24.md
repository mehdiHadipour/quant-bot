# V27.24 — Comprehensive Workflow/Config Audit

Triggered by the user asking whether backtest symbols were updated —
which surfaced a critical bug and prompted a full, systematic audit
rather than a single spot-fix.

## Critical bug found: the LIVE bot workflow never actually picked up
   V27.22's symbol policy

`.github/workflows/bot.yml` sets `SYMBOLS` via
`${{ vars.SYMBOLS || '<hardcoded fallback>' }}`. That hardcoded fallback
still had the OLD, full 14-symbol list — including `BTCUSDT`, `ETHUSDT`,
`XRPUSDT`, `ADAUSDT`, `SUIUSDT`, `TONUSDT`, all of which V27.22 was
supposed to remove entirely. Since this fallback is a GitHub Actions
expression evaluated BEFORE the Python process even starts, it
completely overrides `config.py`'s Python-level default — meaning
**unless the user had manually created a `SYMBOLS` repository Variable
in GitHub with the new list, the live bot has been trading/alerting on
the old symbol set this whole time**, regardless of what `config.py`
said. This is the same bug class found and fixed for `ATR_TP_MULTIPLIER`
in `backtest.yml` a few rounds ago (V27.17.1) — that earlier fix was
scoped to just that one variable in just that one workflow; this round
did a full audit instead of assuming it was isolated.

**Fixed**: `bot.yml`'s `SYMBOLS` fallback now matches V27.22's actual
policy.

## Full systematic audit — 3 more real issues found

Comparing every `config.py` variable against what's actually wired into
each workflow file (not just the one that prompted the question):

1. **`SELL_ONLY_SYMBOLS` (V27.22's own new feature) was never added to
   `bot.yml` at all** — a live run relying on a GitHub Variable override
   for this would have silently had no effect. Added.
2. **`SILENCE_GAP_MULTIPLIER` was also missing from `bot.yml`** (pre-existing
   gap, not from this session's recent changes, but caught by the same
   audit). Added.
3. **`backtest.yml`'s manual-trigger `symbols` input default** was still
   `"BTCUSDT,ETHUSDT,SOLUSDT"` — same bug class as the `bot.yml` one,
   in the manual backtest workflow. Fixed to match the current crypto
   symbol list (this workflow's data source, `fetch_historical_klines.py`,
   is Binance-only, so it can't include the WEEX-routed commodity symbols
   in this particular default).
4. **`scripts/run_adaptive_backtest.py`'s `--symbols` default** had the
   same stale value. Fixed — and while in that file, added an explicit
   `"⚠️_WARNING"` field directly into its JSON report output, stating
   plainly that this report is from the separate, simplified
   continuous-portfolio-weight research model, NOT the live bot's actual
   trades — self-documenting now instead of relying on this being
   explained again in chat every time it comes up (it has, several
   times, across this project).

Also updated for consistency (illustrative examples/docs, not
independently executable defaults, so lower severity): `.env.example`'s
`SYMBOLS` line (added `SELL_ONLY_SYMBOLS` alongside it too),
`README.md`'s example command, and `scripts/run_backtest.py`'s docstring
usage example.

## New regression guard

`scripts/validate_project.py` now cross-checks every top-level
`config.py` variable against `bot.yml`'s wired `vars.X` references —
if a future config variable is added but never wired into the live
workflow, this check fails loudly instead of silently shipping a
setting that can never actually be changed via GitHub Variables. This
only checks that a variable is WIRED (present), not that a hardcoded
`|| 'default'` fallback value is itself still correct when a Python
default changes — that half still needs a human check, same as this
round's `SYMBOLS` fix.

## Testing

172 tests, all passing (no test count change this round — the fixes
were config/workflow files, not application logic; the new
`validate_project.py` check was verified by manual execution in both
the clean and simulated-broken states, since that script isn't
structured as importable/unit-testable functions).
