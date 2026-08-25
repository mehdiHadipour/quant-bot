# V27.16 — Backtest-Driven Findings (multi-round)

The user supplied a real backtest run (backtest_results.csv +
adaptive_backtest_report.json) for review. Two real, separate problems were
found and fixed.

## 1. The two backtest reports contradicted each other — and the trustworthy
   one showed a losing strategy

`adaptive_backtest_report.json` (from `adaptive_backtest_engine.py`) claimed
+4798% return / Sharpe 4.57. `backtest_results.csv` (from
`scripts/run_backtest.py`, which calls the SAME `analyze_market()`/
`can_open_trade()` functions `main.py` uses live) showed the opposite: 2550
closed trades, **13.7% win rate**, net **-282R**. These aren't two views of
the same strategy — `adaptive_backtest_engine.py` / `multi_market_backtest.py`
test a different, simplified continuous-portfolio-weight model
(`adaptive_strategy.signal_and_weight()`) that does not correspond to the
discrete SL/TP trades the live bot actually places and alerts on via
Telegram. The rosy headline number does not describe what this bot does with
real capital; `backtest_results.csv` does.

**Root cause identified**: the default AdaptiveTrend signal path in
`indicators.py` (`ADAPTIVE_TREND_ENABLED=true`) had NO trend-strength filter
at all — only a realized-volatility regime check. It's a bare EMA(6)/EMA(18)
crossover on 4H, which flips direction on every wiggle in a genuinely choppy
market. At the configured SL/TP ratio (ATR×1.8 / ATR×3.0, ~1.67R avg win),
breakeven needs ~19% win rate; the backtest measured ~14%. The legacy scoring
path already required `ADX >= MIN_ADX` for exactly this reason — the
AdaptiveTrend path never did.

**Fix**: `indicators.py`'s AdaptiveTrend branch now also requires
`adx >= MIN_ADX` (reusing the existing 1H ADX already computed and
NaN-checked earlier in the function) before returning a signal. This is a
reasoned fix for a real, identified gap — **not a guarantee of
profitability**. Re-run `scripts/run_backtest.py` against your own data to
see its actual effect before trusting it with real capital.

New tests: `TestAdaptiveTrendAdxGate` in `tests/test_indicators.py` — a
choppy random-walk gets skipped for weak ADX, a strong deterministic trend
still produces a signal (proving the gate doesn't block genuine trends).
The earlier `TestAdaptiveTrendPathDoesNotCrash` regression test was updated
to patch `MIN_ADX` to 0 for its own narrow purpose (proving no NameError),
since it isn't testing the ADX gate itself.

## 1b. First attempt at the fix above was insufficient — a second, real
    bug in the fix itself

The user re-ran the backtest after the ADX-gate fix landed. Result: trade
count dropped 2550 -> 1789 (the gate IS filtering something), but win rate
barely moved (13.7% -> 13.3%) and the strategy was still net-losing
(-172.8R). The fix wasn't working.

**Root cause**: the first version of the gate reused the module-level `adx`
variable — computed from the 1H timeframe (`df`). But the AdaptiveTrend
signal's direction comes entirely from 4H EMAs (`fast_a`/`slow_a`, both
computed from `df_4h`). Filtering a 4H-based trend decision by 1H trend
strength is a timeframe mismatch: 1H can look choppy while 4H is genuinely
trending, and vice versa — so the gate wasn't screening the thing that
actually determines the signal.

**Fix**: compute ADX from `df_4h` instead, matching the timeframe the
direction itself comes from. New regression test
(`test_uses_4h_adx_not_1h_adx`) proves this directly: a choppy 1H frame
paired with a cleanly-trending 4H frame must still produce a signal, since
the gate is supposed to check the 4H trend, not the unrelated 1H one.

**This is now the SECOND attempt at the same backtest finding** — which is
itself worth taking seriously as a signal: fixing a strategy's win rate by
inspection/hypothesis alone is unreliable, confirmed by watching the first
attempt fail empirically. Re-run the backtest again after this change. If
the win rate still doesn't move meaningfully, the more likely explanation
at that point is that a bare EMA(6)/EMA(18) crossover doesn't have a
viable edge on these instruments/period at all, regardless of which
timeframe's ADX gates it — and the fix that would actually need testing
next is real multi-timeframe confirmation (the same 15m+1H+4H+1D
confluence the legacy scoring path already has), not another
single-filter tweak.

## 1c. Second re-run: the corrected ADX-timeframe fix STILL barely moved
    the win rate — real multi-timeframe confluence added

Third backtest re-run, after the 4H-ADX fix: trades 1789 -> 1461, win rate
13.3% -> 12.9% (essentially flat, arguably slightly worse), still net
losing (-170R). The 1c section above's prediction played out: correcting
the ADX timeframe mismatch was necessary but not sufficient — the
underlying EMA(6)/EMA(18) crossover does not appear to have a standalone
edge on this data, confirmed empirically across three consecutive backtest
runs rather than assumed from a single one.

**Fix**: added genuine top-down multi-timeframe confluence to the
AdaptiveTrend path — the 1D trend (EMA50 vs EMA200, via the existing
`get_timeframe_bias()` helper already used elsewhere) must agree with the
4H signal's own direction, or the signal is skipped. This mirrors what the
legacy scoring path already does (multiple timeframes must agree before a
signal counts as real) rather than relying on any single timeframe's
crossover or trend-strength reading alone. Fails OPEN (does not block)
when 1D history is insufficient — consistent with how other optional
confirmations (e.g. funding_rate) already behave in this function: a
missing higher-timeframe opinion should never itself block a signal, only
an opinion that actively disagrees should.

New tests: `TestAdaptiveTrendDailyConfluence` — agreeing daily trend allows
the signal, a contradicting daily trend blocks it, insufficient daily data
fails open rather than blocking. The earlier `test_uses_4h_adx_not_1h_adx`
test was also tightened to pass a properly-trending `df_1d` (instead of
reusing the intentionally-choppy 1H frame for it), isolating what it tests
from this new gate's behavior.

**IMPORTANT, again**: this is now the THIRD change made in response to the
same single backtest finding. Re-run `scripts/run_backtest.py` again and
look at the win rate before trusting any of this with real capital. If
this STILL doesn't help, the honest conclusion is that this signal (in its
current form) may not have a tradeable edge on this data at all — and at
that point, `scripts/validate_robustness.py` (walk-forward folds + Monte
Carlo, from an earlier round) is the right next tool, not another
single-mechanism patch to `indicators.py`.

## 2. `scripts/fetch_weex_historical.py` would have crashed any commodity
   backtest

Requested: add oil/metals (gold, silver, crude oil, natural gas) to the
tradeable symbol set. These were **already present** — `XAUUSDT`, `XAGUSDT`,
`CLUSDT`, `NATGASUSDT` are in `config.py`'s default `SYMBOLS`, already routed
through WEEX in `data_engine.py`, and already covered by the
`COMMODITY_SYMBOLS`/diversification-cap logic from the V27.13/V27.14 rounds.
Nothing needed adding there.

What WAS broken: `scripts/fetch_weex_historical.py` (for building historical
CSVs to backtest these symbols) wrote CSVs with no `taker_buy_volume` column,
but `indicators.py` accesses `df['taker_buy_volume']` unconditionally on
every call — so any backtest attempt against this script's old output would
have crashed with a `KeyError`, not just produced a slightly-off number. It
also only fetched one interval per invocation and had no warmup-window
concept, unlike the Binance equivalent (`fetch_historical_klines.py`).

**Fix**: rewrote the script — adds `taker_buy_volume=0.0` to every row
(matching `data_engine.fetch_weex_klines()`'s live behavior; WEEX's public
endpoint doesn't expose a taker-buy split, and `analyze_market()`'s
order-flow scoring already treats this as neutral rather than fabricating a
number), loops over all 4 intervals by default, and adds the same
`--warmup-days` concept the Binance script has. See the script's own
docstring for a caveat: the historical endpoint it calls could not be
verified against WEEX's live API in this environment (no network access
here) — sanity-check the first run's output before trusting a full backtest
on it.

## Backtesting non-crypto symbols — needs to be run from an environment with
   internet access (this one has none)

```bash
python scripts/fetch_weex_historical.py --symbols XAUUSDT,XAGUSDT,CLUSDT,NATGASUSDT --days 180
python scripts/fetch_historical_klines.py --symbols BTCUSDT,ETHUSDT,SOLUSDT --days 180
python scripts/run_backtest.py --symbols XAUUSDT,XAGUSDT,CLUSDT,NATGASUSDT,BTCUSDT,ETHUSDT,SOLUSDT
python scripts/validate_robustness.py --input backtest_data/backtest_results.csv
```
(`run_backtest.py` mixes crypto and commodity symbols in one run without
issue — same CSV schema, same file-naming convention, same functions.)

## Testing

132 tests, all passing (offline `ta`-library reimplementation, real Wilder's
ADX — see prior round's notes on why this matters for local verification;
the real `ta` package should still be re-verified in CI, which
`.github/workflows/bot.yml` already does automatically).
