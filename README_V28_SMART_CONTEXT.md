# Quant Bot V28 — Smart Context

This release keeps the existing multi-timeframe strategy and adds a final decision gate:

1. 4H trend + 1D confluence
2. 1H technical score: EMA/MACD/RSI/Stochastic/Volume/Structure/Bollinger/Wick
3. Liquidity Sweep + FVG + rolling VWAP
4. Funding rate (Binance -> Bybit fallback)
5. 15m EMA20 confirmation
6. **Smart Context final gate:**
   - Footprint/Order-flow proxy from taker-buy volume
   - Absorption proxy from wick + opposing flow
   - UTC market session filter
   - Optional Whale bias sidecar
   - Optional Fundamental score sidecar
7. Portfolio risk gate: R/R, daily loss, open risk, same-direction concentration

Important: the footprint is explicitly a proxy because the current Binance kline feed does not contain tick-level bid/ask trades. No synthetic tick data is created. For true historical footprint testing, supply historical tick/aggregate-trade data.

Whale and fundamental data are optional. If absent, they are NEUTRAL, never fabricated.

## Direction restrictions
Use repository Variables only after out-of-sample validation:
- `BUY_ONLY_SYMBOLS=...`
- `SELL_ONLY_SYMBOLS=...`

Do not hard-code restrictions from a small backtest sample.

## Required secrets
`TELEGRAM_TOKEN`, `TELEGRAM_CHAT`, `ENCRYPTION_KEY`.


## V28.1 Final All-Markets Update
- BTCUSDT and ETHUSDT are always included in the configured symbol universe.
- All symbols are BUY+SELL by default; one-way policies are disabled unless `ENABLE_DIRECTION_POLICY=1`.
- Rollover/low-liquidity hours are no longer a hard blackout by default. `SESSION_VETO_ENABLED=0`.
- ADX and ATR dead-market filters were loosened to 20 and 0.25% respectively; they remain protective rather than removing the filters entirely.
- Live news is disabled automatically in backtest mode to prevent look-ahead bias. Historical fundamental data should be supplied as a timestamped sidecar if it is to affect backtests.
- Validation no longer renames files during a validation run.

## V28.2 — Real Hyperliquid whale confirmation + WEEX TradFi symbols

**Whale bias is now real, not a manual sidecar.** `scripts/update_whale_bias.py`
runs hourly (`.github/workflows/whale_bias.yml`) and reads Hyperliquid's
public, no-auth API directly (the same on-chain data HyperDash itself is
built on — HyperDash has no public API of its own, so this goes to the
source instead of scraping its UI):
- `stats-data.hyperliquid.xyz/Mainnet/leaderboard` for the most profitable
  traders (ranked by realized PnL over the trailing month, min $50k account
  value).
- `api.hyperliquid.xyz/info` (`batchClearinghouseStates`) for those traders'
  currently open positions.

Positions are aggregated per coin, weighted by notional size (a $5M
position outweighs a $5K one), into `whale_bias.json`
(`{"BTC": {"bias": "BUY", "confidence": 0.82, ...}, ...}`). `main.py` points
`WHALE_BIAS_FILE` at this file, so `smart_context.py`'s existing whale-bias
gate (unchanged) now confirms/vetoes signals against real top-trader
positioning instead of a manually-maintained JSON. Deliberately **not**
wired into `backtest.yml` — using today's live whale positions to score a
year-old backtest candle would be look-ahead bias, the same reason
`NEWS_ENABLED=0` in backtests above.

**WEEX TradFi tokenized products** (`weex_data_engine.py`) add gold, silver,
oil/gas, forex, tokenized US stocks, and indices to the tradable universe,
fetched from WEEX's public spot kline API (`api-spot.weex.com`) instead of
Binance. This uses WEEX's **spot** klines (not its separate perpetual-futures
contract API) as price input, and these are tokenized/synthetic USDT-settled
instruments tracking the underlying price, not the underlying commodity,
currency, or equity itself.

Default `WEEX_SYMBOLS` (one representative per asset, to avoid firing several
near-identical correlated signals for the same underlying move):
`XAUUSDT, XAGUSDT, COPPERUSDT` (metals), `CLUSDT, NATGASUSDT` (energy),
`EURUSDT, GBPUSDT, JPYUSDT, AUDUSDT` (forex), `NVDAUSDT, AAPLUSDT, TSLAUSDT,
AMZNUSDT, COINUSDT` (stocks), `SPYUSDT, QQQUSDT` (indices).

Full confirmed WEEX TradFi list (from the user's own app screenshots,
2026-08-27) if you want to override `WEEX_SYMBOLS` with more:
- Commodities: `NGUSDT`, `NATGASUSDT`, `CLUSDT` (WTI oil), the Brent-oil one
  shown as "OIL(BZ)USDT" in-app (ticker inferred as `BZUSDT`, unverified)
- Metals: `XAUUSDT`, `XAGUSDT`* (silver, inferred), `COPPERUSDT`, `XCUUSDT`
  (a second copper listing), `SLVUSDT` (iShares Silver ETF), `PAXGUSDT` /
  `XAUTUSDT` (two more tokenized-gold variants), `XPDUSDT`* (palladium,
  inferred), `XPTUSDT`* (platinum, inferred), `XALUSDT`* (aluminium, inferred)
- Forex: `EURUSDT`, `GBPUSDT`, `JPYUSDT`, `AUDUSDT`, `CADUSDT`, `CHFUSDT`,
  `BRLUSDT`
- Stocks: `NVDAUSDT`, `AAPLUSDT`, `TSLAUSDT`, `AMZNUSDT`, `COINUSDT`,
  `MSTRUSDT`, `ORCLUSDT`, `PLTRUSDT`, `FUTUUSDT`, `RDDTUSDT`
- Indices: `SPYUSDT`, `QQQUSDT`, `TQQQUSDT` (3x leveraged), `SOXXUSDT`,
  `SOXLUSDT` (3x leveraged), `XLEUSDT`, `EWJUSDT`, `EWYUSDT`, `EWTUSDT`,
  `IEFAUSDT`
- Pre-IPO (illiquid/highly volatile -- not recommended for an automated
  technical-analysis bot, included here only for completeness):
  `ANTHROPICUSDT`, `OPENAIUSDT`, `ENFLAMEUSDT`, `MOONSHOTUSDT`

\* = ticker inferred from WEEX's own consistent in-app naming pattern
("COMMONNAME(TICKER)USDT" -> the API symbol is TICKER+USDT, confirmed
directly for PAXG and XAUT), not independently verified against the live
API. If wrong, that single symbol just fails to fetch and is skipped
(logged as a WARNING) -- it cannot break fetching for any other symbol.

Adding many more of these at once meaningfully increases every 5-minute
cycle's request count (`fetch_all_klines` fetches 4 timeframes per symbol).
The `bot.yml` job timeout was raised from 8 to 12 minutes and the
kline-fetch thread pool from 12 to 24 workers to give headroom for the
larger default symbol set; widen further if you add most/all of the list
above. `WEEX_ENABLED=0` disables all WEEX symbols entirely.

## V28.4 — CRITICAL fix: the live bot could never actually trade + a real backtest engine

**Critical bug fixed.** `main.py`'s `process_symbol()` referenced `result`
and `msg` (the analyzed-signal dict and the alert-message string) roughly
25 lines *before* either was ever assigned — a misplaced block, almost
certainly from an earlier edit that landed in the wrong spot. This raised
`UnboundLocalError` the instant any symbol reached that point with valid
1H/4H data, which is the normal case. In practice: **the live 5-minute
cycle could never successfully analyze a single symbol** — every cycle
would have logged a crash for every symbol, every 5 minutes, indefinitely.
None of the existing checks (`py_compile`, imports, `validate_project.py`,
`system_audit.py`, or any unit test) executed deep enough into
`process_symbol()`'s ~250-line body to catch this, because none of them
actually ran the function against realistic multi-timeframe data. Fixed by
moving the block to after both variables exist. `tests/test_main_process_symbol.py`
is a new regression test that forces a real signal through the full
`process_symbol()` path (mocking only the network calls) specifically so
this class of bug — a variable-ordering mistake deep inside a large
function — can never again pass CI silently.

**Real backtest engine**, replacing the old placeholder that just printed
"No dataset runner configured" and did nothing:
- `scripts/fetch_historical_klines.py` downloads historical OHLCV for
  every configured symbol/interval, routing each symbol to WEEX or
  Binance exactly like the live bot does.
- `scripts/run_backtest.py` walks forward through history and reuses the
  **actual production functions** — `indicators.analyze_market()`,
  `trade_monitor.check_trailing_stop()` / `check_open_trades()`,
  `risk_engine.can_open_trade()` — rather than a separate
  reimplementation, so results reflect what the live bot would really
  have done. All symbols share one portfolio `state["trades"]` list, so
  the portfolio-wide risk gates (`MAX_CONCURRENT_TRADES`,
  `MAX_OPEN_RISK_R`, `MAX_DAILY_LOSS_R`, `MAX_SAME_DIRECTION_OPEN`) are
  exercised exactly as they would be live. `SMART_CONTEXT_MODE=backtest`
  and `NEWS_ENABLED=0` are forced at the top (no live-news look-ahead),
  and `WHALE_BIAS_FILE`/`WHALE_BIAS_JSON` are explicitly cleared (no
  today's-real-whale-positions look-ahead either).
- `.github/workflows/backtest.yml` now actually fetches data and runs
  both scripts, with `symbols`/`days`/`skip_fetch` dispatch inputs, and
  uploads `backtest_report.txt` + `backtest_results.csv` + the fetched
  CSVs as a downloadable artifact. Fetching+backtesting the full default
  symbol set over many days can take a while — narrow `symbols` for a
  faster iteration loop, or use `skip_fetch: true` to reuse data already
  in `backtest_data/` from a previous run.

## V28.5 — Historical fetch was serial and blew past the job timeout

`scripts/fetch_historical_klines.py` fetched every (symbol, interval)
combination one at a time -- 30 symbols x 4 intervals = 120 sequential
HTTP round-trips, each itself paginating page-by-page with a polite sleep
between calls. With the default 30-symbol universe this took 20+ minutes
just for the fetch step alone, leaving the actual backtest computation no
room before the job's `timeout-minutes` cancelled the whole run outright
(observed: "Fetch historical klines" 20m16s, then "Backtest" force-killed
after 9m41s at the 30-minute job ceiling).

Fixed by fetching all (symbol, interval) jobs concurrently with a thread
pool (`--workers`, default 12) instead of one at a time -- a mocked timing
test confirms this is dramatically faster than the old serial loop. Also:
retry/backoff on a failed page was widened (3 attempts -> 6, with
increasing backoff) since concurrent load makes transient rate-limit
hiccups on any single job more likely, so one job doesn't silently lose
data it would have gotten with a bit more patience. The workflow's
default `days` was also lowered from 180 to 90 for a faster default run
(raise it explicitly for a more thorough backtest), and `timeout-minutes`
raised from 30 to 45 for headroom on top of the parallelized fetch.



## V28.6 — CRITICAL fix: the backtest could never produce a single signal

The first real backtest run (30 symbols, 90 days) closed **zero** trades.
Root cause, confirmed by replaying the exact same gate logic against the
real fetched data: `analyze_market()` requires `MIN_CANDLES` (210) candles
of history on **every** timeframe it checks, including 1D — but
`fetch_historical_klines.py --days 90` only ever gave the 1D CSV 90 rows.
`get_timeframe_bias(df_1d)` silently returns `None` whenever
`len(df_1d) < 210`, and the 1D-confirmation gate then unconditionally
rejects every signal (`daily_bias is None` always fails the check). Since
210 daily candles means 210 *days*, and the old default (even the
original 180 before V28.5) never fetched that much 1D history, **this
gate could never once pass, for any symbol, at any default `--days`
setting** — the backtest was structurally guaranteed to close zero trades
regardless of market conditions. Live trading was never affected by this
specific issue: `main.py` always fetches up to 300 candles per timeframe
live, comfortably above 210 even on 1D.

Fixed in `fetch_historical_klines.py`: each interval now fetches
`--days` (the actual simulation window) *plus* however many extra
lead-in days that timeframe needs to have `MIN_CANDLES` of warm-up
available from day 1 of the window, plus a small flat safety margin. For
a 90-day simulation this means fetching roughly 15m=108d, 1h=114d,
4h=140d, and **1d=315d** — the 1D fetch is now deliberately much larger
than the requested window, because 210 of those days are pure warm-up the
1D-confirmation gate needs before it can ever agree or disagree with the
4H bias. `run_backtest.py`'s own tick-skip threshold
(`MIN_1H_HISTORY`) was also changed from an arbitrary `60` to import the
real `indicators.MIN_CANDLES` constant directly, so the two stay in sync
by construction instead of by coincidence.

## V28.7 — First real backtest results: signal engine confirmed working, but all 16 WEEX symbols failed to fetch

The 1D-warmup fix worked: a real backtest run (14 crypto symbols, 90 days)
closed 764 trades with clean, internally consistent mechanics -- `r_multiple`
lands in exactly the expected discrete tiers (1.667 for a full TP hit,
matching `ATR_TP_MULTIPLIER / ATR_SL_MULTIPLIER = 3.0 / 1.8`; 0.5/0.0/-1.0
for trailing-stop tiers), confirming `analyze_market()` + the real
`trade_monitor`/`risk_engine` functions are working correctly together.
Result: an 11% win rate and -134R total over this window/symbol set --
a legitimate (not a bug) finding worth tuning around, not something this
fix addresses.

**All 16 WEEX symbols failed to fetch** ("missing/empty historical CSVs")
and were skipped entirely. The WEEX spot kline endpoint this integration
targets was never independently verified against the live API from this
development environment (network access here is restricted), so the exact
cause isn't confirmed yet. Hardened both `weex_data_engine.py` (the live
bot's fetcher) and `fetch_historical_klines.py`'s WEEX path to:
- accept either a bare array response (like Binance) or a
  `{"data": [...]}` / `{"result": [...]}` enveloped response, instead of
  assuming one shape and mis-parsing (or crashing on) the other
- print/log the actual HTTP status and a body snippet on any failure
  instead of just "empty/skipped"

`.github/workflows/backtest.yml` now also saves the "Fetch historical
klines" step's own output to `fetch_report.txt` and uploads it
(`if: always()`, so it uploads even if a later step fails) -- previously
only the Backtest step's log was captured, so there was no way to see
*why* WEEX failed after the fact. Run the backtest again and check
`fetch_report.txt` in the new artifact for `[WEEX diag]` lines -- that
will show the real HTTP status/body and pin down the exact fix needed.
WEEX symbols currently fail soft (skipped, not crashing anything) in both
backtest and live trading, so leaving `WEEX_ENABLED=1` while this gets
diagnosed is safe, just not yet producing any WEEX signals.

## V28.8 — CRITICAL fix: trades were never actually tracked, ever

Real Telegram screenshots showed signals being announced correctly (full
detail: SL/TP, Smart Context, risk sizing) but the daily performance
report permanently stuck at "برد: 0 | باخت: 0 | نرخ برد: 0.0% ... معاملهٔ
باز فعلاً وجود ندارد" -- forever, no matter how many signals fired.

Root cause: `.github/workflows/bot.yml` declared `permissions:
contents: write` (signalling intent to persist something) and runs
`python main.py`, which relies on `state_manager.py`'s
`state/state.json.enc` (open trades, win/loss stats, cooldowns,
circuit breaker) and `data/history.csv.enc` (closed-trade history)
surviving between the cron's 5-minute runs -- but **the workflow never
actually committed either back to the repo**. Every GitHub Actions run is
a fresh, disposable VM: whatever `main.py` wrote locally to `state/` and
`data/` during a run was simply discarded when that run's VM was torn
down. The next scheduled run, five minutes later, checked out the repo
fresh, found no state file, and started over from a blank slate every
single time -- forever. This meant: a signal could fire and get announced
correctly (that logic doesn't need persisted state), but the trade it
opened was never actually watched across cycles for its SL/TP outcome, so
it could never resolve into a recorded win or loss, and the portfolio-wide
risk gates (`MAX_CONCURRENT_TRADES`, `MAX_OPEN_RISK_R`,
`MAX_DAILY_LOSS_R`, "already open" per-symbol checks) were also
operating on a permanently-empty view of the world.

Fixed by adding a "Persist state" step to `bot.yml` after `python
main.py` runs, committing `state/` and `data/` back to the repo --
the exact same pattern `whale_bias.yml` was already using correctly for
`whale_bias.json`. Also added a permanent regression guard to
`scripts/validate_project.py`: it now fails validation if `bot.yml` ever
declares `contents: write` + runs `main.py` without an actual `git
add/commit/push` step touching `state/` -- verified by temporarily
reintroducing the bug and confirming the validator catches it.

## V28.9 — Ichimoku Kinko Hyo added to signal detection

`indicators.compute_ichimoku()` adds the standard 9/26/52 Ichimoku Cloud
as a real, weighted component of `total_score` -- not just a display
line. It's implemented by hand (rolling max/min over pandas, not a
library indicator) so the Senkou-span forward-shift is unambiguous:
"today's" cloud is the raw Senkou A/B value computed from data as of 26
candles ago (since Senkou spans are traditionally plotted 26 candles
*ahead* of the data used to compute them) -- a common off-by-one mistake
in hand-rolled Ichimoku code that this implementation specifically tests
against (`tests/test_ichimoku.py`, including a trend-reversal case).

Four classic Ichimoku reads are combined into one score (range -40..+40,
comparable in magnitude to trend_score/momentum_score):
- price vs. cloud (above/below/inside): ±15
- Tenkan-sen vs. Kijun-sen cross: ±10
- cloud color (Senkou A vs B, "bullish/green" or "bearish/red"): ±5
- Chikou span vs. price 26 candles ago: ±10

This is folded into `total_score` exactly like every other component
(trend, momentum, stochastic, Bollinger, etc.) -- not a hard gate, so it
genuinely influences whether a signal clears `MIN_SIGNAL_PROBABILITY` and
which direction it leans, without being an all-or-nothing veto. It fails
soft (score 0, never blocks a signal on its own) when there isn't yet 78
candles of history or when `ICHIMOKU_ENABLED=0`.

The Telegram alert now shows a `☁️ Ichimoku:` line (cloud position,
Tenkan/Kijun cross, cloud color, Chikou confirmation, combined score) so
it's visible that it's actually being used, not just computed silently.
`scripts/run_backtest.py` needed no changes -- since Ichimoku is folded
into `total_score` before `direction` is decided inside `analyze_market()`
itself, the backtest automatically reflects it.

## V28.10 — CRITICAL fix: backtest was O(N^2), killed by the job timeout at 41+ minutes

A real run (30 symbols, 90 days) showed "Fetch historical klines" finishing
quickly (3m9s -- the V28.5 parallelization is working great) but
"Backtest" running for 41m47s before being force-cancelled at the
45-minute job ceiling.

Root cause: `run_backtest.py`'s walk-forward loop passed
`df_1h_full.iloc[:idx+1]` (and the equivalent growing slice for 4H/1D/15m)
to `analyze_market()` at **every single tick** -- as `idx` climbs into the
thousands over a 90-day walk, every indicator (EMA200, rolling ADX,
Bollinger, etc.) was recomputed over that whole, ever-larger series each
time. Total work for one symbol's walk scales O(N^2) in the number of
ticks; live trading never hits this because `data_engine.fetch_klines`
always returns a fixed ~300-candle window, never a growing one.

Fixed by bounding every timeframe slice to `LOOKBACK_CANDLES = 300`
(matching that same live fetch limit) before calling `analyze_market()` --
turning total work linear in the number of ticks instead of quadratic. A
synthetic benchmark at realistic data scale (2736 hourly candles/symbol,
matching a real 90-day fetch) went from correctly-still-running-past-40-
minutes to **47 seconds for 5 symbols (~4.7 minutes extrapolated to 30)**.

This surfaced a second, smaller bug: once the lookback window starts
sliding (past candle 300), `df_1h_full.iloc[start:idx+1]` keeps the
*original* row labels (e.g. 512..812) instead of a fresh 0-based index --
which broke `detect_rsi_divergence()`'s `.loc[...]` lookups with a
`KeyError` the moment the window first slid. Fixed by `.reset_index(drop=True)`
on every sliced DataFrame, which also makes each slice match exactly what
live trading's freshly-fetched DataFrames always look like (always a
fresh 0-based index, since each cycle constructs a brand new DataFrame
from the API response). `tests/test_run_backtest_window.py` is a new
regression test that walks past `LOOKBACK_CANDLES` rows specifically to
confirm this doesn't crash again.
