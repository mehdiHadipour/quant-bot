# V27.23 — Real Footprint Data (Informational Only)

## Correcting an earlier, overly broad answer

Previously said footprint/order-flow needs tick-level data unavailable
without a major architecture change. That's half right: genuine
footprint data DOES need individual trades (not candle aggregates), but
Binance's public `GET /api/v3/aggTrades` endpoint serves recent trades
via a plain REST call — no WebSocket or persistent connection needed, so
it fits the existing 10-minute cron cycle without any architecture
change. Verified via web search this round.

## What was added

- `data_engine.fetch_recent_agg_trades(symbol, minutes=55)` — real,
  individual trade data (price/qty/aggressor side) for the recent window,
  capped under Binance's hard 1-hour startTime/endTime limit for this
  endpoint. Crypto-only (Binance-specific; WEEX-routed
  commodity/forex/index symbols have no equivalent).
- `footprint.py` (new module) — `compute_footprint_metrics()` derives a
  real point-of-control (the price level with the most traded volume,
  not just the candle's open/close), where that concentration sits
  within the candle's range, and buy/sell imbalance split by zone
  (near-high vs. near-low) — genuinely more granular than the existing
  `taker_buy_volume`-based `buy_ratio`, which is already an accurate
  aggregate but only at whole-candle resolution.
- Wired into `main.py`: for crypto symbols, fetches and computes this
  after a signal is generated, appends one line to the Telegram message.

## Why this is informational-only, not a gate — an important, deliberate
   exception to this project's usual discipline

Every other signal added in this project was validated against 2 years
of real backtested trade outcomes first (see the long history of
rejected ideas: RSI extremity, candle-aggregate order-flow/CVD, entry
timing, hour-of-day, multi-touch S/R — all tested and rejected; ADX,
multi-timeframe confluence, the profit-lock tiers — tested and kept).
This one skips that step out of necessity: Binance's aggTrades endpoint
only serves recent data, and bulk historical tick data for a genuine
2-year backtest is many GB per symbol — not fetchable or storable here,
and likely impractical even in a free GitHub Codespace.

Consequently `footprint.py`'s module docstring is explicit: this must
stay informational (shown in the Telegram message, never blocking a
signal) until enough live, forward-observed outcomes accumulate to check
whether it actually correlates with results — the same test-before-trust
standard used everywhere else in this project, just applied going
forward instead of retroactively. A test (`test_never_claims_to_be_a_
validated_filter`) guards the message wording against ever implying
otherwise.

Fails open on any error (rate limit, network issue, malformed response)
— wrapped in main.py so a footprint fetch/compute failure can never
block or delay signal delivery.

## Testing

172 tests, all passing. 19 new: `tests/test_footprint.py` (14, covering
buy-ratio computation, POC location for both directions, near-high/
near-low imbalance split, and the informational-wording regression
guard) and `tests/test_agg_trades.py` (5, covering the real fetch,
empty/error handling, and the 55-minute window cap).

## Other items from this round

- **Hour-of-day filter**: tested against real data, rejected. Hourly
  expectancy pattern from the first half of the 2-year dataset had a
  -0.373 correlation with the second half's pattern — i.e. actively
  inconsistent, meaning any "bad hours" identified were noise, not a
  real effect. Not implemented.
- **Mobile app as a local compute engine**: not attempted this round —
  a genuinely separate, large undertaking (rewriting Python trading
  logic for Android, or embedding a Python runtime) distinct from the
  existing companion app (which only displays GitHub Actions run status
  today). Flagged for a deliberate, separate decision rather than folded
  into this round.
- **Backtesting the new symbol direction policy** (DOGEUSDT/DOTUSDT/
  ZECUSDT bidirectional; BNBUSDT/SOLUSDT/AVAXUSDT/LINKUSDT/NEARUSDT
  SELL-only): still blocked on real historical data for everything
  except SOLUSDT (already covered in V27.22's release notes) — this
  project has never had real candle data for ZECUSDT, DOGEUSDT,
  DOTUSDT, BNBUSDT, AVAXUSDT, or LINKUSDT. Commands to fetch and send
  this data remain in V27.22's release notes.
