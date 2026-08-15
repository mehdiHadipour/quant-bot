#!/usr/bin/env python3
"""
🚀 AI Quant Bot v25.12 - Two-Stage Trailing Stop (Lock Partial Profit) + 10-Minute Cycle
The single biggest lever left for real average-R improvement, chosen
deliberately over chasing the low-weight (±8) funding-rate issue further:
check_trailing_stop() previously had ONE stage — move SL to breakeven at
50% progress to TP, then nothing further until TP or a full reversal
back to exactly 0R. That means every trade that gets most of the way to
target and then reverses banks NOTHING, even after doing almost
everything right. Added a second stage: once price reaches
PARTIAL_LOCK_TRIGGER_R (default 75%) of the way to TP, SL moves to lock
in PARTIAL_LOCK_R (default 0.5R) of REAL profit instead of just
breakeven. A trade that gets close to target and reverses now banks
+0.5R instead of 0R — direct, mechanical improvement to average R across
exactly the "almost made it" trades that were previously worth nothing.
Needs "initial_risk" (frozen at trade-open, v25.6+) to know what one R
means in price terms; older trades without it simply keep the old
single-stage behavior, nothing breaks. check_trailing_stop()'s return
shape changed from a bare list of trades to a list of
{"trade":..., "stage": "breakeven"|"partial_lock"} dicts so callers can
message each stage accurately; main.py and the risk-guide text sent with
every signal were both updated to describe this precisely and only
describe real automated behavior. 6 new tests cover both directions,
progressive multi-cycle triggering, a candle jumping straight past both
thresholds, the legacy-trade fallback, and that R-multiple crediting on
an eventual full win still stays correct afterward — all 25 tests in
test_trade_monitor.py pass.

Also: CYCLE_MINUTES default changed 5→10 and bot.yml's cron updated to
match (requested directly, and independently sound: the strategy runs
on 1h/4h/1d candles where 5 vs 10 minute polling makes no real
difference, while it doubles the silence-watchdog's alert threshold
(30min→60min), meaningfully cutting false alerts from GitHub's
documented scheduling jitter without weakening real-outage detection).

v25.11 - Diagnose Persistent Funding Rate 0/N
Live reports have shown "Funding Rate 0/N موفق" on EVERY reported cycle
since v25.4 shipped — never intermittent, always both sources failing
together. That's a systemic pattern, not the occasional transient
network blip the earlier message assumed (worth checking: Bybit, like
Binance, may also restrict its API from US-based cloud IPs, which is
where GitHub Actions runners live — unconfirmed, this update exists to
find out for certain). fetch_funding_rate() now returns a third value,
fail_reason, with the actual HTTP status/error from BOTH the Binance and
Bybit attempts. main.py captures it from only the first failing symbol
per cycle (avoids repeating the same systemic reason 14 times) and
prints it in the existing "no funding data this cycle" info line, e.g.
"نمونهٔ دقیق: BTCUSDT: Binance HTTP 451 | Bybit HTTP 451" — replacing
the previous generic "probably a temporary network issue" guess with
the exact code. Purely diagnostic — no change to scoring or behavior;
still fails open, still ±8 weight max, still never blocks a signal.

v25.10 - Critical Fix: history.csv Corruption + Cron Jitter Note
Fixes a real bug found live: "Could not read history.csv for performance
ratios: Error tokenizing data. C error: Expected 13 fields in line 7,
saw 14". Root cause: append_to_history() wrote pd.DataFrame([trade]) as
literally whatever keys happened to be on the trade dict that cycle —
so the column SET silently changed the moment the trade dict's shape
changed between versions (v25.6 added "initial_risk" to every newly-
opened trade). A row closed before that change (13 columns) and a row
closed after it (14 columns) ended up in the SAME file, which pandas
can't parse back — reproduced exactly with a synthetic file matching
the reported error. Fixed with an explicit, fixed HISTORY_COLUMNS
schema that every future row always follows regardless of what other
fields exist on the live trade dict, plus a self-healing reader
(_read_history_csv) that detects a schema mismatch or unparseable file,
tolerantly re-reads it (dropping only the specific malformed row(s)),
and rewrites it once under the current schema — tested end-to-end
against a reproduction of the exact reported corruption, including
verifying values re-map to the correct named columns (not just
position) after repair. This self-heals your existing history.csv
automatically on the next run; no manual GitHub edit needed.

Also: the "silence watchdog" (v25.5) firing at 154 minutes was investigated
and is a real, separately-documented GitHub Actions limitation, not a
bot bug — GitHub's own docs and community reports confirm 5-minute cron
schedules are best-effort and can be delayed 30-60+ min (occasionally
more) under high platform load, especially at the top of every hour.
bot.yml's cron changed from "*/5 * * * *" to "3-59/5 * * * *" to avoid
landing on the worst-contention :00 mark — reduces, but per GitHub's own
documentation cannot fully eliminate, this class of delay. If
near-guaranteed timing is ever needed, the only real fix is an external
scheduler pinging workflow_dispatch, which is a bigger, separate change
not made here.

v25.9 - Remove HYPEUSDT (Futures-Only, No Spot Data Available)
Fixes a real issue found live: HYPEUSDT logged "Failed to fetch data
from all endpoints" on every timeframe, every single cycle, after being
added in v25.7. Root cause: Binance's GLOBAL platform (binance.com) only
lists HYPE as a FUTURES contract — its spot market (HYPE/USDT) exists
only on the separate Binance.US exchange. fetch_klines() only ever
queries binance.com's public SPOT mirrors, which simply don't carry
HYPEUSDT at all, so every mirror failed for every timeframe (400 or
451 depending on the mirror) — harmless (fails open, never affected any
other symbol; the cycle itself completed successfully every time) but
pure log noise, forever, for a symbol that could never actually produce
a signal. Removed from the default SYMBOLS list. Default is back to 14
symbols. Lesson applied going forward: any future symbol addition needs
a confirmed binance.com SPOT listing specifically, not just a futures
one — the two aren't always the same set for every coin.

v25.8 - Add SUI, TON, NEAR
Adds SUIUSDT, TONUSDT, NEARUSDT to the default SYMBOLS list — all three
confirmed listed and liquid on Binance USDT-M futures, all established
large-cap L1s with meaningful volatility. Deliberately did NOT add any
very-low-cap/meme names: their outsized "volatility" numbers come from
thin order books and manipulation risk, not genuine tradeable structure
— the opposite of what this bot's ADX/structure gates are built to
find. Default list is now 15 symbols (was 10 as of v25.1). As before,
SYMBOLS remains fully overridable via the "SYMBOLS" GitHub repo
Variable with no code change needed.

v25.7 - Add ZEC/HYPE, Fix Node.js 20 Deprecation Warning
Adds ZECUSDT and HYPEUSDT to the default SYMBOLS list (both confirmed
listed on Binance USDT-M futures, both notably volatile recently) —
though note SYMBOLS was already fully overridable via the "SYMBOLS"
GitHub repo Variable without any code/zip change at all; this only
updates the *default* used when that variable isn't set. Also bumps
actions/checkout (v4→v6) and actions/setup-python (v5→v6) in bot.yml to
versions with native Node.js 24 support, clearing the "Node.js 20 is
deprecated" annotation seen in the Actions UI — purely a CI housekeeping
fix, no effect on trading logic.

v25.6 - Critical Fix: Wins Recorded as 0.0R After Trailing
Fixes a real bug found by comparing live results against the code: the
daily report showed a healthy 60% win rate (3W/2L) but negative equity
(-1.00R, average -0.20R/trade) — a mismatch that shouldn't be possible
at this bot's TP:SL ratio (3.0/1.8 ≈ 1.67R per full win) unless wins
were being under-credited.

Root cause: check_open_trades() computed r_multiple's risk_distance from
the trade's CURRENT "sl" field. But check_trailing_stop() legitimately
moves sl to breakeven (== entry) once price is TRAILING_TRIGGER_R (0.5,
i.e. halfway) toward TP — and since halfway is always reached before
TP (1.0) by construction, essentially every trade that goes on to hit
full TP has ALREADY had its sl moved to entry by then. risk_distance
became exactly 0, falling into the `else: r_multiple = 0.0` branch —
silently recording every such win as 0.0R instead of its real reward,
while genuine losses still recorded correctly. Reproduced exactly with
the reported numbers (3×0.0 + a mix of losses summing to -1.0 = -1.00R
total, -0.20R average) — see the two new tests in test_trade_monitor.py.

Fix: trades now store "initial_risk" (= abs(entry - original sl)) at
open time in main.py, frozen before any trailing can touch it.
check_open_trades() uses this frozen value for r_multiple's denominator
instead of the live (possibly-trailed) sl, falling back to the old
live-sl calculation only for trades opened before this fix (which lack
the field). state_manager.py backfills "initial_risk" once for any
already-open legacy trade on the next load — recovering the true
original risk for any not yet trailed to breakeven, and changing
nothing (same fallback as before) for ones already trailed, since the
true original SL can no longer be recovered for those. Net effect for
currently-open trades: correct going forward for whichever haven't been
trailed yet by the time this deploys; unavoidably still 0.0R-if-trailed
for the rest, one time only, as those specific pre-fix trades close out.

v25.5 - Silence Watchdog
Adds: check_silence_gap(), called at the start of every cycle. Tracks
"last_cycle_completed_at" in state and alerts via Telegram if more than
SILENCE_GAP_MULTIPLIER × CYCLE_MINUTES (default 30 min) has passed since
the previous completed cycle. This catches what none of the existing
checks can: the GitHub Actions workflow itself being paused, disabled
(e.g. free-tier minute cap hit on a private repo), or several
consecutive top-level crashes — as opposed to check_fetch_health, which
only detects "the script ran but got no market data." Without this, the
only symptom visible from a phone is silence, which is indistinguishable
from "market's just quiet, no signals this cycle" (normal and frequent
given this bot's strict multi-gate filters). Self-resolving: fires at
most once per real gap, since the timestamp updates the moment a cycle
runs again. An intentional circuit-breaker pause also updates the
timestamp so it's never mistaken for the bot being down.
Context: requested as a general "what else can genuinely be improved
for free, given mobile+GitHub-only constraints" pass — most defensive
groundwork (crash alerts, connectivity alerts, cooldowns, atomic state
writes with backup) was already in place from earlier versions; this
was the one clear remaining gap.

v25.4 - Bybit Funding-Rate Fallback (fixes 451 on GitHub Actions)
Fixes: fetch_funding_rate() only ever tried Binance's fapi.binance.com,
which returns HTTP 451 (geo-blocked) from GitHub Actions' US-based runner
IPs essentially every cycle — so funding_ok was consistently 0/10, not a
bug in scoring but a genuinely missing data source. Rather than trying to
bypass Binance's own access restriction (which would violate its Terms
of Service and risk the account), this adds a second, independent public
source: Bybit's unauthenticated v5 market-data endpoint, tried only if
Binance fails. It's a different exchange's number — close to Binance's in
practice via cross-exchange arbitrage, but not identical — so the
Telegram message and logs now say explicitly which exchange the number
actually came from whenever the fallback fires, instead of silently
presenting it as Binance's. fetch_funding_rate() now returns (rate,
source) instead of a bare float; the only caller (main.py) was updated
to match. No change to indicators.py or analyze_market()'s funding_rate
parameter (still a plain float/None) or funding_score weighting.

v25.3 - ICT Liquidity Sweep Confluence
Adds: a new, independent confluence score based on the ICT "liquidity
sweep" concept — a candle whose wick pierces beyond a recent 20-candle
swing high/low (the same level structure_score already uses for
breakouts, where stop-loss orders commonly cluster) but then CLOSES back
inside that range. This is the classic "stop hunt then reversal" pattern,
the mirror-opposite read of a genuine breakout continuation, and is
mutually exclusive with the existing breakout score by construction (a
breakout requires the close to stay BEYOND the level; a sweep requires it
back INSIDE). Purely derived from OHLC data already being fetched — no
new API calls. Requested after a discussion about adding liquidity-based
confluence to the scoring model. Not a guarantee of improved performance
— it's one more legitimate, bounded-weight vote in the existing
multi-factor score, same as FVG/VWAP/order-flow; real effect on win rate
can only be judged from live results over time.

v25.2 - "Why No Signal?" Diagnostic Logging
Fixes: every cycle previously logged "📊 Analyzing SYMBOL..." and then, if
no signal fired, nothing else — a silent skip. From the log alone there
was no way to tell "the strategy correctly found nothing tradable" apart
from "a bug is suppressing a real setup" (the exact question raised after
a cycle showed 0/10 signals while BTC and ETH both looked like they had
clear moves on the chart). analyze_market() now accepts an optional
`reasons` list and appends a specific, human-readable explanation at
every point it returns "no signal" (ADX below threshold, confidence below
MIN_SIGNAL_PROBABILITY with the actual buy/sell probabilities shown, 1D
trend disagreeing with 4H, 15m momentum not yet confirming...). main.py
logs that reason at INFO level right after each "Analyzing..." line, so
the very next cycle's log answers the question directly instead of
requiring a code review. Purely additive — return values/shapes for
existing callers are unchanged, so this doesn't alter which signals fire,
only what gets logged when one doesn't.

v25.1 - Funding Rate Log-Noise Fix
Fixes: fetch_funding_rate() was logging a full WARNING for every one of
the 10 symbols on every 5-minute cycle when Binance's futures API
(fapi.binance.com) is geo-blocked from GitHub Actions' US-based runner
IPs — which happens consistently, not occasionally, since derivatives
trading is more strictly geo-restricted than spot. This was ~2,900 near-
identical noise lines/day for a structural limitation, not a bug to keep
warning about. Now: per-symbol failures are silent (debug-level), and the
cycle logs one aggregated "Funding Rate موفق: X/10" line instead, with a
one-time explanatory note if it's fully unavailable. The feature itself
was already correctly fail-open (funding_score stays 0, never blocks a
signal) — this fix is purely about log noise, not correctness.

Everything else unchanged from v25.0: Funding rate (Binance USDT-M
futures, free) as a contrarian scoring input, MAX_CONCURRENT_TRADES
portfolio-wide cap, atomic state writes (temp file + os.replace, so a
mid-write kill can never corrupt state), and all earlier features: v24
VWAP + Fair Value Gap, v23 full-candle-range TP/SL/trailing/warning
detection, wick/order-flow scoring, v22 real automated trailing stop,
5-minute check interval, v21 state-persistence fix, v20 SELL-signal-
symmetry fix, multi-timeframe confluence, R-multiple dashboard,
structured logging, self-healing state, consecutive-fetch-failure
alerting, ADX/Bollinger/Stochastic + RSI divergence warnings, per-symbol
cooldown, 10-symbol coverage, parallel fetch, daily reports.
"""

from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed
import pandas as pd
import os
import io
import sys

from config import (
    validate_runtime_secrets,
    SYMBOLS, CRYPTO_SYMBOLS, COMMODITY_SYMBOLS, ATR_SL_MULTIPLIER, ATR_TP_MULTIPLIER,
    RISK_PERCENT_PER_TRADE,
    MAX_CONCURRENT_TRADES, CYCLE_MINUTES, SILENCE_GAP_MULTIPLIER,
    MAX_DAILY_LOSS_R, MAX_OPEN_RISK_R, MIN_REWARD_RISK, MAX_SAME_DIRECTION_OPEN,
    PARTIAL_LOCK_TRIGGER_R, PARTIAL_LOCK_R, TRAILING_TRIGGER_R,
    MAX_OPEN_PER_MARKET_GROUP, DIVERSIFICATION_ENABLED,
)
from data_engine import fetch_market_klines, fetch_funding_rate
from indicators import analyze_market
from trade_monitor import (
    check_open_trades,
    check_sl_warnings,
    check_trailing_stop,
    is_symbol_on_cooldown,
    update_circuit_breaker,
)
from state_manager import load_state, save_state, _get_fernet
from telegram import send_telegram_alert
from logger import log
from risk_engine import can_open_trade, performance_throttle_multiplier

# v27.3: history is now encrypted at rest (data/history.csv.enc), reusing
# the exact same Fernet key/mechanism as state.json.enc — added because
# this repo can be Public (recommended earlier for free unlimited Actions
# minutes), and a PLAINTEXT trade history committed every cycle would
# expose full trade-by-trade detail (symbols, directions, entry/exit,
# R results) to anyone visiting the repo. Not a secrets leak (no keys are
# in it) but a real strategy/performance privacy exposure worth closing.
HISTORY_FILE = "data/history.csv.enc"
_LEGACY_PLAINTEXT_HISTORY_FILE = "data/history.csv"  # pre-v27.3; migrated once, then removed

# Fixed, explicit schema for history.csv — deliberately NOT derived from
# whatever keys happen to be on a trade dict at close time. Before v25.10,
# append_to_history() wrote pd.DataFrame([trade]) as-is, so the column
# SET silently changed whenever the trade dict's shape changed between
# code versions — e.g. v25.6 added "initial_risk" to every newly-opened
# trade. Rows written before vs. after that change ended up with a
# different column count in the SAME file (13 vs 14), which pandas can't
# parse back ("Expected 13 fields... saw 14") — a real corruption found
# live. Every row from now on always has exactly these columns, in this
# order, regardless of what other operational fields (status,
# sl_warning_sent, etc.) exist on the live trade dict; anything missing
# is written empty rather than shifting every later column.
HISTORY_COLUMNS = [
    "time", "symbol", "direction", "entry", "sl", "tp", "initial_risk",
    "exit_time", "exit_price", "result", "r_multiple",
]


def _decimals_for_reference_price(price):
    """How many decimal places to show for a symbol's prices, based on
    its typical price level (using the signal's own entry price as the
    reference) — computed ONCE per message and applied to every related
    number (entry/SL/TP/ATR/VWAP/exit) so they stay visually consistent
    within one alert.

    Fixes a real bug: every price field previously used a fixed
    f"{value:,.2f}" — fine for BTC (~117,000.00) but for a sub-$1 coin
    like DOGEUSDT (~0.07) or DOTUSDT, entry/SL/TP/ATR/VWAP all rounded
    to the same "0.07", making them visually indistinguishable and
    hiding real information (e.g. ATR showing "0.00" even when the
    actual value was a meaningful 0.8% of price). Deliberately computed
    from the reference price's own magnitude, not a per-symbol lookup
    table — Binance's actual tickSize/precision per symbol would need a
    dedicated API call and ongoing maintenance as symbols are added;
    this approximates it well enough for human-readable alerts, which is
    all this is used for (never for order precision/rounding, since this
    bot is signal-only and never places real orders)."""
    try:
        price = abs(float(price))
    except (TypeError, ValueError):
        return 2
    if price == 0 or price >= 1:
        return 2
    if price >= 0.1:
        return 4
    if price >= 0.01:
        return 5
    if price >= 0.001:
        return 6
    if price >= 0.0001:
        return 7
    return 8


def format_price(value, decimals):
    """Format a single number at the given decimal count (from
    _decimals_for_reference_price), with thousands separators."""
    try:
        value = float(value)
    except (TypeError, ValueError):
        return str(value)
    return f"{value:,.{decimals}f}"

# Timeframes fetched for every symbol each cycle:
#   15m — short-term momentum confirmation (final entry-timing gate)
#   1h  — primary indicator/entry timeframe (unchanged core logic)
#   4h  — trend bias
#   1d  — higher-timeframe trend agreement (confluence gate)
INTERVALS = ["15m", "1h", "4h", "1d"]


# Binance returns the currently-forming candle as the final row. A forming
# candle can change every few seconds and can therefore flip EMA/MACD,
# structure, VWAP, order-flow, wick and FVG readings between bot cycles.
# It is fine for monitoring an already-open trade, but unsafe for a new
# directional decision. Signal generation therefore uses completed candles
# only; trade management keeps the live candle.
def _closed_candles(df):
    """Return completed candles, excluding the exchange's live final row."""
    if df is None or df.empty:
        return df
    if len(df) < 2:
        return df.iloc[0:0].copy()
    return df.iloc[:-1].copy()


def prepare_analysis_frames(klines_for_symbol):
    """Split fetched candles into live monitoring and closed analysis frames."""
    live = {interval: klines_for_symbol.get(interval) for interval in INTERVALS}
    closed = {interval: _closed_candles(live[interval]) for interval in INTERVALS}
    return live, closed

# If every single symbol fails to fetch data for this many consecutive
# cycles (15 min each), something is systemically wrong (network, Binance
# fully blocked, etc.) rather than a one-off blip — worth a one-time alert.
FETCH_FAILURE_ALERT_THRESHOLD = 4


def _write_history_df(df):
    """Serialize a history dataframe to CSV text, encrypt it with the
    same Fernet key as state.json.enc, and write it atomically (temp
    file + rename) so an interrupted write never leaves a half-written
    or corrupted encrypted file on disk."""
    os.makedirs("data", exist_ok=True)
    csv_text = df.to_csv(index=False)
    encrypted = _get_fernet().encrypt(csv_text.encode())
    tmp_path = HISTORY_FILE + ".tmp"
    with open(tmp_path, "wb") as f:
        f.write(encrypted)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp_path, HISTORY_FILE)


def _decrypt_history_file(path):
    """Read + decrypt a history file at `path`, returning the raw CSV
    text (not yet parsed) so callers can choose a normal vs. tolerant
    pandas read."""
    with open(path, "rb") as f:
        encrypted = f.read()
    return _get_fernet().decrypt(encrypted).decode()


def _read_history_csv():
    """Read + decrypt data/history.csv.enc, self-healing a schema
    mismatch left over from before v25.10 (see HISTORY_COLUMNS above).
    Tries a normal read first; on a column-count parser error, falls
    back to a tolerant read that drops only the specific malformed
    row(s), reindexes everything to the current fixed schema, and
    rewrites the file once — so this heals permanently instead of
    warning every single cycle forever.

    v27.3: also handles a ONE-TIME migration if an old plaintext
    data/history.csv exists from before encryption was added — reads it,
    encrypts it into the new file, deletes the plaintext original, and
    returns the data normally. From the next commit onward only the
    encrypted file exists in the repo.
    """
    if not os.path.exists(HISTORY_FILE):
        if not os.path.exists(_LEGACY_PLAINTEXT_HISTORY_FILE):
            return None
        try:
            df = pd.read_csv(_LEGACY_PLAINTEXT_HISTORY_FILE)
        except Exception as e:
            log.warning(f"Legacy plaintext history.csv could not be parsed normally ({e}); attempting a tolerant repair...")
            try:
                df = pd.read_csv(_LEGACY_PLAINTEXT_HISTORY_FILE, on_bad_lines="skip", engine="python")
            except Exception as e2:
                log.warning(f"Could not migrate legacy plaintext history.csv, leaving it untouched: {e2}")
                return None
        df = df.reindex(columns=HISTORY_COLUMNS)
        _write_history_df(df)
        try:
            os.remove(_LEGACY_PLAINTEXT_HISTORY_FILE)
        except OSError as e:
            log.warning(f"Encrypted history.csv.enc written, but could not remove old plaintext copy: {e}")
        log.info(f"✅ history.csv رمزنگاری شد و به history.csv.enc منتقل شد ({len(df)} ردیف).")
        return df

    try:
        csv_text = _decrypt_history_file(HISTORY_FILE)
        return pd.read_csv(io.StringIO(csv_text))
    except Exception as e:
        log.warning(f"history.csv.enc could not be decrypted/parsed normally ({e}); attempting a tolerant repair...")
        try:
            csv_text = _decrypt_history_file(HISTORY_FILE)
            df = pd.read_csv(io.StringIO(csv_text), on_bad_lines="skip", engine="python")
            df = df.reindex(columns=HISTORY_COLUMNS)
            _write_history_df(df)
            log.info(f"✅ history.csv.enc repaired: {len(df)} row(s) kept under the current fixed schema.")
            return df
        except Exception as e2:
            log.warning(f"Could not repair history.csv.enc, leaving it untouched: {e2}")
            return None


def append_to_history(trade):
    """Append a closed trade to the encrypted history file, always using
    the fixed HISTORY_COLUMNS schema — never whatever raw keys happen to
    be on `trade` this cycle (see HISTORY_COLUMNS above for why). Reads
    the whole (small — one row per closed trade) file, appends in
    memory, and re-encrypts, since Fernet tokens can't be appended to
    directly the way a plaintext file can."""
    row = {col: trade.get(col, "") for col in HISTORY_COLUMNS}
    new_row_df = pd.DataFrame([row], columns=HISTORY_COLUMNS)
    existing = _read_history_csv()
    combined = (
        pd.concat([existing, new_row_df], ignore_index=True)
        if existing is not None else new_row_df
    )
    combined = combined.reindex(columns=HISTORY_COLUMNS)
    _write_history_df(combined)


def fetch_all_klines(symbols):
    """Fetch 15m/1h/4h/1d candles for every symbol concurrently.

    This is the main time cost of a cycle (one HTTP round-trip per
    symbol/interval). Fetching them in parallel instead of sequentially
    keeps a 10-symbol x 4-timeframe cycle (40 requests) well inside the
    GitHub Actions job timeout.
    """
    jobs = {}
    results = {symbol: {interval: None for interval in INTERVALS} for symbol in symbols}

    with ThreadPoolExecutor(max_workers=min(12, len(symbols) * len(INTERVALS) or 1)) as executor:
        for symbol in symbols:
            for interval in INTERVALS:
                jobs[executor.submit(fetch_market_klines, symbol, interval)] = (symbol, interval)

        for future in as_completed(jobs):
            symbol, interval = jobs[future]
            try:
                results[symbol][interval] = future.result()
            except Exception as e:
                log.error(f"Error fetching {symbol} {interval}: {e}")
                results[symbol][interval] = None

    return results


def recent_realized_r_multiples(lookback=20):
    """Last `lookback` CLOSED trades' r_multiple values, oldest-first, for
    performance_throttle_multiplier(). Reads the same encrypted history
    already used by current_daily_loss_r(); returns [] on any read
    problem so the throttle degrades to its safe default (1.0, no
    throttle) rather than ever raising."""
    df = _read_history_csv()
    if df is None or df.empty or "r_multiple" not in df.columns:
        return []
    if "exit_time" in df.columns:
        try:
            df = df.assign(_exit_dt=pd.to_datetime(df["exit_time"], errors="coerce", utc=True))
            df = df.sort_values("_exit_dt")
        except Exception:
            pass
    values = []
    for r in df["r_multiple"].tail(lookback):
        try:
            values.append(float(r))
        except (TypeError, ValueError):
            continue
    return values


# What the strategy's own research/backtest promises as a realistic
# per-trade expectancy, in R — used only as the reference point for
# performance_throttle_multiplier() below, never to alter signal
# generation itself. Deliberately conservative (well under the headline
# backtest expectancy) since README.md already flags that the supplied
# backtest is a research result on limited data, not a live guarantee;
# a throttle reference set at the optimistic headline number would fire
# on almost every normal live session.
BASELINE_EXPECTANCY_R = 0.15


def build_risk_tip(direction, price, sl, tp):
    """Position-sizing guidance is informational (the bot doesn't know the
    person's real account balance), but both trailing stages describe
    ACTUAL automated behavior — see check_trailing_stop()."""
    risk_per_unit = abs(price - sl)
    halfway = price + (tp - price) * TRAILING_TRIGGER_R if direction == "BUY" else price - (price - tp) * TRAILING_TRIGGER_R
    lock_point = price + (tp - price) * PARTIAL_LOCK_TRIGGER_R if direction == "BUY" else price - (price - tp) * PARTIAL_LOCK_TRIGGER_R
    lock_price = price + risk_per_unit * PARTIAL_LOCK_R if direction == "BUY" else price - risk_per_unit * PARTIAL_LOCK_R
    d = _decimals_for_reference_price(price)

    throttle = performance_throttle_multiplier(
        recent_realized_r_multiples(), baseline_expectancy_r=BASELINE_EXPECTANCY_R
    )
    throttle_note = ""
    if throttle < 1.0:
        throttle_note = (
            f"\n⚠️ عملکرد واقعی معاملات اخیر ضعیف‌تر از انتظار پژوهشی است — "
            f"پیشنهاد می‌شود اندازهٔ پوزیشن این سیگنال را به {throttle:.0%} مقدار معمول کاهش دهید "
            f"(هشدار نرم؛ معاملهٔ خودکار متوقف نشده — آن فقط با ۳ باخت پیاپی فعال می‌شود)."
        )

    return (
        f"\n💡 <b>راهنمای مدیریت ریسک</b>:\n"
        f"• اندازهٔ پوزیشن پیشنهادی برای ریسک {RISK_PERCENT_PER_TRADE:.1f}٪ سرمایه:\n"
        f"  (سرمایهٔ شما × {RISK_PERCENT_PER_TRADE:.1f}٪) ÷ {format_price(risk_per_unit, d)}\n"
        f"• 🔒 Trailing خودکار، دو مرحله‌ای:\n"
        f"  ۱) وقتی قیمت به {format_price(halfway, d)} برسد، SL به نقطهٔ ورود ({format_price(price, d)}) منتقل می‌شود — دیگر ریسکی ندارد.\n"
        f"  ۲) وقتی قیمت به {format_price(lock_point, d)} برسد، SL به {format_price(lock_price, d)} منتقل می‌شود — یعنی حتی با برگشت کامل، "
        f"{PARTIAL_LOCK_R:.2f}R سود واقعی برایتان قفل شده، نه فقط بدون‌ضرر.\n"
        f"نیازی نیست خودتان دستی این کارها را انجام دهید."
        f"{throttle_note}"
    )


def has_reached_max_concurrent_trades(state):
    """True if the number of currently-open trades (across all symbols)
    has already reached MAX_CONCURRENT_TRADES. A value of 0 disables the
    cap entirely."""
    if MAX_CONCURRENT_TRADES <= 0:
        return False
    open_count = sum(1 for t in state["trades"] if t.get("status") == "open")
    return open_count >= MAX_CONCURRENT_TRADES


def current_daily_loss_r():
    """Read current-day realized loss in R for the portfolio risk gate."""
    df = _read_history_csv()
    if df is None or df.empty or "exit_time" not in df.columns or "r_multiple" not in df.columns:
        return 0.0
    today = datetime.now(timezone.utc).date().isoformat()
    total = 0.0
    for exit_time, r in zip(df["exit_time"].astype(str), df["r_multiple"]):
        try:
            dt = datetime.fromisoformat(exit_time.replace("Z", "+00:00"))
            value = float(r)
            if dt.date().isoformat() == today and value < 0:
                total += abs(value)
        except (ValueError, TypeError):
            continue
    return total


def process_symbol(state, symbol, klines_for_symbol, counters):
    log.info(f"📊 Analyzing {symbol}...")

    # Trade management needs the LIVE (still-forming) 1H candle so
    # intrabar TP/SL/trailing touches aren't missed — see _closed_candles
    # above for why signal generation deliberately does NOT use it.
    live_1h = klines_for_symbol.get("1h")

    # Directional analysis is locked to completed candles. The live final
    # candle is retained separately for TP/SL/trailing monitoring.
    _, closed = prepare_analysis_frames(klines_for_symbol)
    df_15m = closed["15m"]
    df_1h = closed["1h"]
    df_4h = closed["4h"]
    df_1d = closed["1d"]

    # NOTE: these are pandas DataFrames or None.
    # Never use `not df` on a DataFrame — its truth value is ambiguous
    # and raises a ValueError. Always compare explicitly to None.
    if df_1h is None or df_4h is None or df_1h.empty or df_4h.empty:
        log.warning(f"Skipping {symbol}: no completed 1h/4h market data available.")
        return

    counters["fetched_ok"] += 1

    # Trade management uses the LIVE 1H candle so intrabar TP/SL/trailing
    # touches are not missed. Signal generation below uses completed candles.
    if live_1h is not None and not live_1h.empty:
        current_high = live_1h["high"].iloc[-1]
        current_low = live_1h["low"].iloc[-1]
        current_close = live_1h["close"].iloc[-1]
    else:
        current_high = df_1h["high"].iloc[-1]
        current_low = df_1h["low"].iloc[-1]
        current_close = df_1h["close"].iloc[-1]

    # Real, automated trailing-to-breakeven: runs BEFORE the TP/SL-close
    # check below, so if this same candle both crosses the trigger AND
    # reverses hard enough to hit the *new* breakeven stop, it closes at
    # breakeven this cycle rather than waiting. This directly protects
    # against the "reaches ~halfway to TP, then fully reverses and hits
    # the original far-away SL for a full loss" pattern.
    trailing_moves = check_trailing_stop(state, current_high, current_low, symbol)
    if trailing_moves:
        for move in trailing_moves:
            trade = move["trade"]
            d = _decimals_for_reference_price(trade["entry"])
            if move["stage"] == "partial_lock":
                locked_r = PARTIAL_LOCK_R
                send_telegram_alert(
                    f"🔒 <b>سود جزئی قفل شد (Partial Lock)</b> - {symbol}\n"
                    f"جهت: {trade['direction']}\n"
                    f"قیمت ورود: {format_price(trade['entry'], d)}\n"
                    f"SL جدید: {format_price(trade['sl'], d)}\n"
                    f"قیمت فعلی: {format_price(current_close, d)}\n"
                    f"از این لحظه، حتی اگر بازار کامل برگردد، این معامله حداقل "
                    f"{locked_r:.2f}R سود واقعی برایتان تضمین کرده — نه فقط بدون‌ضرر."
                )
            else:
                send_telegram_alert(
                    f"🔒 <b>SL به نقطهٔ ورود منتقل شد (Breakeven)</b> - {symbol}\n"
                    f"جهت: {trade['direction']}\n"
                    f"قیمت ورود: {format_price(trade['entry'], d)}\n"
                    f"قیمت فعلی: {format_price(current_close, d)}\n"
                    f"از این لحظه، این معامله دیگر ریسکی برای شما ندارد."
                )
        save_state(state)

    # One-time warning if any open trade on this symbol has drifted close
    # to its stop-loss (checked against the candle's low/high, not just its
    # close, so a brief intrabar dip toward the stop is still caught).
    sl_warnings = check_sl_warnings(state, current_high, current_low, current_close, symbol)
    if sl_warnings:
        for trade in sl_warnings:
            d = _decimals_for_reference_price(trade["entry"])
            send_telegram_alert(
                f"⚠️ <b>هشدار نزدیک‌شدن به SL</b> - {symbol}\n"
                f"جهت: {trade['direction']}\n"
                f"قیمت ورود: {format_price(trade['entry'], d)}\n"
                f"قیمت فعلی: {format_price(current_close, d)}\n"
                f"حد ضرر (SL): {format_price(trade['sl'], d)}\n"
                f"قیمت به نزدیکی حد ضرر رسیده — مراقب باشید."
            )
        save_state(state)

    # Checked against the candle's full high/low range, not just its close
    # price — a brief intrabar touch of TP/SL that recovered by the time
    # the candle closed is still correctly detected as a close here.
    closed_trades = check_open_trades(state, current_high, current_low, current_close, symbol)

    if closed_trades:
        update_circuit_breaker(state, closed_trades)
        for trade in closed_trades:
            append_to_history(trade)
            counters["closed"] += 1
            emoji = "✅" if trade["result"] == "WIN" else "❌"
            r = trade.get("r_multiple", 0.0)
            d = _decimals_for_reference_price(trade["entry"])
            send_telegram_alert(
                f"{emoji} <b>معامله بسته شد</b> - {symbol}\n"
                f"نتیجه: {trade['result']} ({r:+.2f}R)\n"
                f"ورود: {format_price(trade['entry'], d)}\n"
                f"خروج: {format_price(trade['exit_price'], d)}"
            )
        save_state(state)
        # A trade just closed this cycle; wait for the next cycle before
        # opening a new one on the same symbol.
        return

    if is_symbol_on_cooldown(state, symbol):
        log.info(f"🧊 {symbol} در حالت Cooldown است (به‌خاطر ضرر اخیر)، این چرخه رد شد.")
        return

    # Risk control: never stack a second trade on a symbol that already has
    # one open — wait for it to close (TP/SL) first.
    if any(t.get("status") == "open" and t["symbol"] == symbol for t in state["trades"]):
        log.info(f"📌 {symbol} از قبل یک معاملهٔ باز دارد؛ تا بسته‌شدن آن، سیگنال جدید نادیده گرفته می‌شود.")
        return

    # Portfolio-wide risk control: cap total simultaneous open trades across
    # ALL symbols, since several of these symbols (e.g. BTC/ETH/BNB) tend to
    # move together — without this cap, several highly-correlated signals
    # could all open in the same cycle, which is repeated exposure to one
    # market move dressed up as diversification, not real risk spreading.
    if has_reached_max_concurrent_trades(state):
        log.info(
            f"📌 سقف معاملات هم‌زمان ({MAX_CONCURRENT_TRADES}) پر است؛ سیگنال {symbol} این چرخه رد شد."
        )
        return

    # 15m and 1D are used as confluence gates inside analyze_market; if they
    # failed to fetch this cycle, fall back to an empty frame so the
    # relevant checks are skipped gracefully rather than crashing (the 1H/4H
    # core logic — the part that matters most — still runs normally).
    safe_15m = df_15m if df_15m is not None else pd.DataFrame(columns=df_1h.columns)
    safe_1d = df_1d if df_1d is not None else pd.DataFrame(columns=df_1h.columns)

    # Free, optional positioning signal — fetched right before analysis (not
    # in the earlier bulk kline fetch) so a slow/failed funding-rate call
    # never delays or blocks the core 1H/4H analysis for every symbol.
    # Failures are common and expected (see the caveat in data_engine.py)
    # so they're tallied here for a single end-of-cycle summary line
    # instead of a warning logged for every symbol every cycle.
    funding_rate, funding_source, funding_fail_reason = (fetch_funding_rate(symbol) if symbol in CRYPTO_SYMBOLS else (None, None, "TradFi/commodity: funding not applicable"))
    if funding_rate is not None:
        counters["funding_ok"] += 1
        counters.setdefault("funding_by_source", {}).setdefault(funding_source, 0)
        counters["funding_by_source"][funding_source] += 1
    elif "funding_fail_example" not in counters:
        # Only the FIRST failing symbol's exact reason is kept per cycle —
        # live results show this is consistently a systemic failure (both
        # sources down together, every symbol), so one concrete example is
        # far more useful than 14 near-identical lines.
        counters["funding_fail_example"] = f"{symbol}: {funding_fail_reason}"

    skip_reasons = []
    result = analyze_market(
        safe_15m, df_1h, df_4h, safe_1d, symbol, funding_rate=funding_rate, reasons=skip_reasons
    )
    if not result:
        # v25.2: previously this was a silent skip — the log just moved on
        # to the next symbol with no trace of WHY. That made it impossible
        # to tell "the strategy correctly found nothing" apart from "the
        # strategy is broken and missing real setups" from the log alone.
        # Now every skip states exactly which gate stopped it (ADX, the
        # confidence threshold, 1D/4H disagreement, 15m confirmation...).
        reason = skip_reasons[-1] if skip_reasons else "دلیل نامشخص (بررسی کد لازم است)"
        log.info(f"🔍 {symbol}: بدون سیگنال — {reason}")
        return

    atr = result["atr"]
    direction = result["direction"]
    # Direction/indicators come from the last COMPLETED 1H candle. Use the
    # latest live price as the entry reference so SL/TP are not stale.
    price = current_close

    sl = price - (atr * ATR_SL_MULTIPLIER) if direction == "BUY" else price + (atr * ATR_SL_MULTIPLIER)
    tp = price + (atr * ATR_TP_MULTIPLIER) if direction == "BUY" else price - (atr * ATR_TP_MULTIPLIER)

    # V27.13 defined MAX_OPEN_PER_MARKET_GROUP/DIVERSIFICATION_ENABLED for
    # the multi-market (crypto + commodity) upgrade but never actually
    # wired them anywhere — found during review. group_symbols is only
    # passed when diversification is enabled AND this symbol is in the
    # (smaller, deliberately-capped) commodity group; the much larger
    # crypto group is intentionally left uncapped here since
    # MAX_SAME_DIRECTION_OPEN and MAX_CONCURRENT_TRADES already guard it.
    group_symbols = COMMODITY_SYMBOLS if (DIVERSIFICATION_ENABLED and symbol in COMMODITY_SYMBOLS) else None

    allowed, risk_reason = can_open_trade(
        state, price, sl, tp, direction,
        max_daily_loss_r=MAX_DAILY_LOSS_R,
        max_open_risk_r=MAX_OPEN_RISK_R,
        min_reward_risk=MIN_REWARD_RISK,
        daily_loss_r=current_daily_loss_r(),
        max_same_direction_open=MAX_SAME_DIRECTION_OPEN,
        symbol=symbol,
        group_symbols=group_symbols,
        max_open_per_group=MAX_OPEN_PER_MARKET_GROUP,
    )
    if not allowed:
        log.warning(f"🛡️ {symbol}: سیگنال به‌دلیل کنترل ریسک رد شد — {risk_reason}")
        return

    d = _decimals_for_reference_price(price)
    msg = f"""
🚨 <b>سیگنال جدید</b> - {result['symbol']}
📊 جهت: {direction}
🕯️ تصمیم بر اساس آخرین کندل کاملاً بسته‌شدهٔ 1H (کندل در حال تشکیل در تشخیص جهت دخالت ندارد)
📈 احتمال BUY: {result['buy']:.1f}%
📉 احتمال SELL: {result['sell']:.1f}%
💰 قیمت ورود: {format_price(price, d)}
🛑 SL: {format_price(sl, d)}
🎯 TP: {format_price(tp, d)}
⚠️ ATR: {format_price(atr, d)} ({(atr / price * 100):.2f}%)
📶 ADX: {result.get('adx', 0):.1f}
📊 فشار سفارش (Taker Buy): {result.get('buy_ratio', 0.5) * 100:.0f}%
📐 VWAP: {format_price(result.get('vwap', 0), d)} (قیمت {'بالای' if price > result.get('vwap', price) else 'زیر'} VWAP)
🧭 تأیید چندتایم‌فریمی: 15m + 1H + 4H + 1D هم‌جهت
"""

    breakdown = result.get("score_breakdown") or {}
    if breakdown:
        breakdown_lines = "\n".join(
            f"  • {name}: {value:+.0f}" for name, value in breakdown.items()
        )
        msg += (
            f"\n🧩 <b>ترکیب امتیاز تصمیم</b> (مجموع: {result.get('total_score', 0):+.1f}):\n"
            f"{breakdown_lines}\n"
        )

    if funding_rate is not None:
        source_note = " — دادهٔ Bybit (بایننس در دسترس نبود)" if funding_source == "bybit" else ""
        msg += f"💸 Funding Rate: {funding_rate * 100:+.4f}٪ (هر ۸ ساعت){source_note}\n"

    fvg = result.get("fvg")
    if fvg:
        msg += f"📦 FVG ({'صعودی' if fvg == 'bullish' else 'نزولی'}) تازه شناسایی شد — تأیید حرکت.\n"

    liquidity_sweep = result.get("liquidity_sweep")
    if liquidity_sweep:
        msg += (
            f"🎣 Liquidity Sweep ({'صعودی' if liquidity_sweep == 'bullish' else 'نزولی'}): "
            f"قیمت سقف/کف نوسان اخیر را شکار کرد و بازگشت — تأیید Smart Money.\n"
        )

    divergence = result.get("divergence")
    if (direction == "BUY" and divergence == "bearish") or (direction == "SELL" and divergence == "bullish"):
        msg += (
            "\n🔀 <b>هشدار واگرایی</b>: واگرایی RSI برخلاف جهت این سیگنال شناسایی شد "
            "(احتمال ضعیف‌شدن مومنتوم) — با احتیاط بیشتری تصمیم بگیرید.\n"
        )

    msg += build_risk_tip(direction, price, sl, tp)

    log.info(msg)
    send_telegram_alert(msg)
    counters["signals"] += 1

    state["trades"].append({
        "symbol": result["symbol"],
        "direction": direction,
        "entry": price,
        "tp": tp,
        "sl": sl,
        # v25.6 fix: "R" must always mean "multiples of the ORIGINAL risk
        # taken", frozen at entry — never a moving target. Stored here,
        # separately from the live "sl" field (which trailing legitimately
        # moves to breakeven), specifically so R-multiple calculations at
        # close time never divide by a shrunk/zeroed-out post-trail
        # distance. See check_open_trades in trade_monitor.py.
        "initial_risk": abs(price - sl),
        "status": "open",
        "sl_warning_sent": False,
        "sl_moved_to_breakeven": False,
        "sl_partial_lock_done": False,
        "time": datetime.now(timezone.utc).isoformat(),
    })
    save_state(state)


def compute_performance_ratios():
    """Trade-based (not time-annualized) Sharpe/Sortino approximations from
    the full closed-trade history, plus the average R per trade. These are
    a reasonable proxy given trades close at irregular intervals (some in
    an hour, some in days) rather than on a fixed schedule, which is what
    textbook annualized Sharpe/Sortino assume — labelled as such in the
    report so they're never mistaken for standard annualized figures."""
    df = _read_history_csv()
    if df is None:
        return None

    if "r_multiple" not in df.columns:
        return None

    r = pd.to_numeric(df["r_multiple"], errors="coerce").dropna()
    if len(r) == 0:
        return None

    avg_r = r.mean()
    std_r = r.std(ddof=1) if len(r) > 1 else 0.0
    sharpe = (avg_r / std_r) if std_r > 0 else None

    downside = r[r < 0]
    if len(downside) > 1:
        downside_std = downside.std(ddof=1)
    elif len(downside) == 1:
        downside_std = abs(downside.iloc[0])
    else:
        downside_std = 0.0
    sortino = (avg_r / downside_std) if downside_std and downside_std > 0 else None

    return {"count": len(r), "avg_r": avg_r, "sharpe": sharpe, "sortino": sortino}


def maybe_send_daily_report(state):
    """Send a once-per-UTC-day performance summary instead of spamming an
    open-trades summary on every 15-minute cycle. Triggers on the first
    cycle of a new UTC calendar day."""
    today = datetime.now(timezone.utc).date().isoformat()
    if state.get("last_report_date") == today:
        return

    stats = state.get("stats", {})
    wins = stats.get("wins", 0)
    losses = stats.get("losses", 0)
    total = wins + losses
    win_rate = (wins / total * 100) if total > 0 else 0.0

    gross_profit = stats.get("gross_profit_r", 0.0)
    gross_loss = stats.get("gross_loss_r", 0.0)
    profit_factor_text = f"{(gross_profit / gross_loss):.2f}" if gross_loss > 0 else "—"

    ratios = compute_performance_ratios()
    if ratios:
        sharpe_text = f"{ratios['sharpe']:.2f}" if ratios["sharpe"] is not None else "—"
        sortino_text = f"{ratios['sortino']:.2f}" if ratios["sortino"] is not None else "—"
        avg_r_text = f"{ratios['avg_r']:+.2f}R"
    else:
        sharpe_text = sortino_text = avg_r_text = "—"

    open_trades = [t for t in state.get("trades", []) if t.get("status") == "open"]
    if open_trades:
        open_lines = "\n".join(
            f"  • {t['symbol']} {t['direction']} — ورود: "
            f"{format_price(t['entry'], _decimals_for_reference_price(t['entry']))}"
            for t in open_trades
        )
    else:
        open_lines = "  (معاملهٔ باز فعلاً وجود ندارد)"

    report = (
        f"📅 <b>گزارش روزانهٔ عملکرد</b>\n"
        f"✅ برد: {wins}  |  ❌ باخت: {losses}  |  نرخ برد: {win_rate:.1f}%\n"
        f"💰 Equity: {stats.get('equity_r', 0.0):+.2f}R  |  📉 Max Drawdown: {stats.get('max_drawdown_r', 0.0):.2f}R\n"
        f"⚖️ Profit Factor: {profit_factor_text}  |  📊 Average R: {avg_r_text}\n"
        f"📐 Sharpe (per-trade, تقریبی): {sharpe_text}  |  Sortino: {sortino_text}\n"
        f"📂 معاملات باز فعلی:\n{open_lines}"
    )
    send_telegram_alert(report)

    state["last_report_date"] = today
    save_state(state)


def check_fetch_health(state, fetched_ok_count, total_symbols):
    """If NO symbol got usable data this cycle, count it as a full-failure
    cycle. After several in a row, send one alert (not a repeat every
    cycle) so the person knows something systemic is wrong — e.g. Binance
    fully unreachable — rather than the bot just going quiet for hours."""
    if fetched_ok_count == 0 and total_symbols > 0:
        state["consecutive_fetch_failures"] = state.get("consecutive_fetch_failures", 0) + 1
        log.warning(f"این چرخه هیچ نمادی داده دریافت نکرد. شمارندهٔ پیاپی: {state['consecutive_fetch_failures']}")

        if (
            state["consecutive_fetch_failures"] >= FETCH_FAILURE_ALERT_THRESHOLD
            and not state.get("fetch_failure_alert_sent")
        ):
            send_telegram_alert(
                f"⚠️ <b>هشدار اتصال</b>\n"
                f"در {state['consecutive_fetch_failures']} چرخهٔ اخیر (هر ۱۵ دقیقه)، هیچ داده‌ای از "
                f"هیچ نمادی دریافت نشد. احتمالاً مشکلی در اتصال به Binance یا شبکهٔ GitHub Actions "
                f"وجود دارد. لطفاً تب Actions مخزن را بررسی کنید."
            )
            state["fetch_failure_alert_sent"] = True
    else:
        if state.get("consecutive_fetch_failures", 0) > 0:
            log.info("اتصال داده دوباره برقرار شد؛ شمارندهٔ خطای پیاپی صفر شد.")
        state["consecutive_fetch_failures"] = 0
        state["fetch_failure_alert_sent"] = False


def check_silence_gap(state):
    """Alert if an unusually large amount of time has passed since the
    last cycle successfully finished. This catches things a normal
    in-cycle check can't: the GitHub Actions workflow being paused,
    auto-disabled, or hitting the free-tier minute cap, or several
    consecutive crashes each swallowed individually by their own
    try/except with no cumulative signal. Without this, the person's
    only clue that something's wrong is the ABSENCE of Telegram
    messages — easy to miss on a phone, especially since "no signal
    this cycle" (normal) looks identical to "the bot never ran"
    (a real problem) from a quiet phone's perspective.
    Silent on the very first-ever run (nothing to compare against) and
    self-resolving: the alert only ever fires once per real gap, since
    the timestamp updates the moment a cycle runs again."""
    last_str = state.get("last_cycle_completed_at")
    if not last_str:
        return
    try:
        last = datetime.fromisoformat(last_str)
        gap_minutes = (datetime.now(timezone.utc) - last).total_seconds() / 60
    except (ValueError, TypeError):
        return

    if gap_minutes > CYCLE_MINUTES * SILENCE_GAP_MULTIPLIER:
        log.warning(f"⏰ فاصلهٔ زیادی از آخرین چرخهٔ کامل‌شده گذشته: {gap_minutes:.0f} دقیقه.")
        send_telegram_alert(
            f"⏰ <b>هشدار سکوت</b>\n"
            f"آخرین چرخهٔ کامل‌شدهٔ ربات حدود {gap_minutes:.0f} دقیقه پیش بود "
            f"(انتظار عادی: هر {CYCLE_MINUTES} دقیقه).\n"
            f"این معمولاً یعنی GitHub Actions موقتاً متوقف شده — لطفاً تب Actions "
            f"ریپازیتوری را چک کنید (رایج‌ترین دلیل: اتمام سقف دقیقهٔ رایگان ماهانه "
            f"روی ریپازیتوری خصوصی، یا غیرفعال‌شدن دستی workflow)."
        )


def should_skip_cycle_early(state):
    """v27.4 (restored — was dropped in the v27.5 package this was merged
    from): the workflow's cron trigger fires every 5 minutes (a frequent
    'heartbeat') instead of exactly every CYCLE_MINUTES — because live
    results showed GitHub's own scheduler dropping/delaying individual
    scheduled runs by 200+ minutes, well beyond documented normal jitter.
    Waiting for the NEXT exact CYCLE_MINUTES-aligned slot after a drop
    means waiting just as long again; a more frequent heartbeat means a
    dropped/delayed trigger has another attempt just 5 minutes later
    instead of up to CYCLE_MINUTES later.

    But the actual expensive work (fetching klines for every symbol,
    running analysis, committing to git) should still only happen once
    every CYCLE_MINUTES, not every 5 — so every heartbeat first checks
    how long it's actually been since the last COMPLETED cycle, and
    exits immediately (no API calls, no git activity, a couple seconds
    of runtime) if it's too soon. This does not change Actions minutes
    billed (GitHub rounds up to 1 minute regardless), only reliability:
    roughly 2x as many chances to actually land a real cycle within any
    given CYCLE_MINUTES window.

    Returns True (skip everything else this run) if a real cycle
    completed too recently; False on the very first-ever run (nothing
    to compare against) or once enough time has passed.
    """
    last_str = state.get("last_cycle_completed_at")
    if not last_str:
        return False
    try:
        last = datetime.fromisoformat(last_str)
        elapsed_minutes = (datetime.now(timezone.utc) - last).total_seconds() / 60
    except (ValueError, TypeError):
        return False
    return elapsed_minutes < CYCLE_MINUTES


def main():
    log.info(f"🚀 Starting cycle - {datetime.now(timezone.utc).isoformat()}")
    state = load_state()

    if should_skip_cycle_early(state):
        log.info(
            f"⏭️ کمتر از {CYCLE_MINUTES} دقیقه از آخرین چرخهٔ کامل گذشته — "
            "این heartbeat بدون انجام کاری رد می‌شود."
        )
        return

    check_silence_gap(state)

    if state.get("circuit_breaker"):
        cb_time = datetime.fromisoformat(state["circuit_breaker"])
        if datetime.now(timezone.utc) < cb_time:
            log.warning(f"🛑 Circuit breaker active until {state['circuit_breaker']}")
            # Still counts as "the bot is alive and ran this cycle" — record
            # it so the silence watchdog doesn't mistake an intentional,
            # already-alerted circuit-breaker pause for the bot being down.
            state["last_cycle_completed_at"] = datetime.now(timezone.utc).isoformat()
            save_state(state)
            return
        else:
            log.info("✅ Circuit breaker expired. Resetting.")
            state["circuit_breaker"] = None
            state["stats"]["streak"] = 0
            save_state(state)

    maybe_send_daily_report(state)

    counters = {"signals": 0, "closed": 0, "fetched_ok": 0, "funding_ok": 0}
    klines = fetch_all_klines(SYMBOLS)

    for symbol in SYMBOLS:
        try:
            process_symbol(state, symbol, klines[symbol], counters)
        except Exception as e:
            # One bad symbol should never take down the whole cycle.
            log.error(f"Error processing {symbol}: {e}")

    check_fetch_health(state, counters["fetched_ok"], len(SYMBOLS))
    state["last_cycle_completed_at"] = datetime.now(timezone.utc).isoformat()
    save_state(state)

    funding_by_source = counters.get("funding_by_source", {})
    funding_source_note = (
        f" (Binance: {funding_by_source.get('binance', 0)}، Bybit: {funding_by_source.get('bybit', 0)})"
        if counters["funding_ok"] > 0 else ""
    )
    log.info(
        f"✅ Cycle completed. سیگنال‌های جدید: {counters['signals']} | "
        f"معاملات بسته‌شده: {counters['closed']} | نمادهای موفق: {counters['fetched_ok']}/{len(SYMBOLS)} | "
        f"Funding Rate موفق: {counters['funding_ok']}/{len(SYMBOLS)}{funding_source_note}"
    )
    if counters["funding_ok"] == 0 and len(SYMBOLS) > 0:
        example = counters.get("funding_fail_example", "دلیل نامشخص")
        log.info(
            f"ℹ️ Funding Rate در این چرخه از هیچ نمادی دریافت نشد (نمونهٔ دقیق: {example}). "
            "ربات از v25.4 هم Binance و هم Bybit را امتحان می‌کند؛ اگر این کد خطا مدام تکرار "
            "شود، احتمالاً یعنی هر دو منبع از IP گیت‌هاب اکشن مسدودند، نه یک قطعی موقت. "
            "ربات بدون این داده هم کاملاً عادی کار می‌کند (امتیاز این بخش صفر در نظر گرفته می‌شود)."
        )


if __name__ == "__main__":
    validate_runtime_secrets()
    try:
        main()
    except Exception as e:
        log.error(f"Fatal error: {e}")
        try:
            send_telegram_alert(f"❌ <b>خطای اجرای ربات</b>\n{e}")
        except Exception:
            pass
        sys.exit(1)
