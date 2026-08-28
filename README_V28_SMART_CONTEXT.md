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
