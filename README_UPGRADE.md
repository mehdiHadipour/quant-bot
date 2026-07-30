# Quant Bot v26 Upgrade Pack

این بسته بر پایهٔ `quant_bot_v25_12_final` ساخته شده و هدف آن افزایش قابلیت اطمینان، تست‌پذیری، امنیت و امکان مدیریت با گوشی اندروید است.

## تغییرات اصلی

### 1. Import-safe configuration
قبلاً نبودن Secretها هنگام import شدن `config.py` باعث `SystemExit` می‌شد و کل test discovery را می‌شکست. اکنون import امن است و فقط هنگام اجرای واقعی `main.py`، `validate_runtime_secrets()` اجرا می‌شود.

### 2. Lazy encryption initialization
`state_manager.py` دیگر هنگام import شدن فوراً Fernet را می‌سازد. این کار تست‌پذیری را بهتر می‌کند و خطای Secret را در زمان مناسب نشان می‌دهد.

### 3. CI سخت‌گیرانه‌تر
Lint و test دیگر `continue-on-error` ندارند. اگر تست یا lint شکست بخورد، چرخهٔ ربات اجرا نمی‌شود. این تصمیم عمداً fail-closed است.

### 4. GitHub Actions رایگان‌تر و قابل پیش‌بینی‌تر
زمان‌بندی پیش‌فرض به ۱۵ دقیقه تغییر داده شده است. GitHub Actions زمان‌بندی را تضمین نمی‌کند؛ بنابراین این ربات برای «سیگنال‌دهی دوره‌ای» طراحی شده، نه اجرای HFT یا سفارش‌گذاری لحظه‌ای.

### 5. تست با Secret موقت
Workflow تست یک Fernet key موقت می‌سازد؛ کلید واقعی شما هرگز برای تست مصرف نمی‌شود.

### 6. Static validation
اسکریپت `scripts/validate_project.py` وجود فایل‌های اصلی، syntax پایتون و نشانه‌های hard-coded secret را بررسی می‌کند.

### 7. Android Companion
پروژهٔ `android-companion/` یک اپ سبک اندرویدی است که هیچ Secret را ذخیره نمی‌کند و برای مدیریت سریع پروژه، باز کردن GitHub Actions و Telegram طراحی شده است. ساخت APK از طریق Workflow جداگانهٔ GitHub انجام می‌شود و APK به‌عنوان Artifact تحویل داده می‌شود.

## معماری پیشنهادی

`Market Data → Indicators → Signal Scoring → Risk Rules → Trade Monitor → Encrypted State → Telegram`

و در کنار آن:

`Android Companion → GitHub Actions / Documentation / Telegram`

اپ اندروید «موتور معامله» نیست؛ این تفکیک عمداً انجام شده تا کلیدهای حساس روی گوشی قرار نگیرند و باتری/اتصال اینترنت گوشی عامل اجرای ربات نباشد.

## محدودیت مهم

هیچ نرم‌افزار معاملاتی را نمی‌توان «کاملاً بدون ایراد» یا «غیرقابل انتقاد» تضمین کرد، به‌خصوص در بازارهای مالی و محیط‌های شبکه‌ای. این نسخه برای کاهش خطاهای قابل پیش‌بینی و افزایش قابلیت تست ساخته شده، اما قبل از استفادهٔ جدی باید با دادهٔ تاریخی و Paper Trading اعتبارسنجی شود.

## راه‌اندازی با گوشی

1. ZIP را استخراج کنید.
2. محتوای پروژه را در GitHub قرار دهید.
3. سه Secret بسازید: `TELEGRAM_TOKEN`، `TELEGRAM_CHAT`، `ENCRYPTION_KEY`.
4. Workflow را دستی اجرا کنید.
5. از تب Actions نتیجه را بررسی کنید.
6. برای ساخت اپ، Workflow با نام `Android Companion Build` را اجرا کنید و APK را از Artifact دریافت کنید.

> برای امنیت، Secretها را هرگز در ZIP، README، اپ اندروید یا کد قرار ندهید.

## v26.1 Pro Hardening

- Fixed a critical state persistence bug where `save_state()` referenced an undefined `fernet` variable.
- Added explicit state schema versioning and migration defaults.
- Added a blocking repository quality gate for pull requests and pushes.
- Added Python syntax and hard-coded-secret validation.
- Added Android Companion v1.1 with GitHub Actions status lookup and direct Actions navigation.
- Kept credentials out of the APK by design.
- Added additional state encryption round-trip tests, including Unicode state.

### Important operational rule
The bot remains **signal-only**. It does not place exchange orders. Any future execution layer should be isolated behind an explicit feature flag and paper-trading gate first.


## v27 Ultimate — Portfolio Risk + Research Hardening

### Portfolio Risk Engine
A new pure Python `risk_engine.py` adds a fail-closed pre-entry gate:
- minimum Reward/Risk ratio (`MIN_REWARD_RISK`, default 1.5R)
- maximum daily realized loss (`MAX_DAILY_LOSS_R`, default 3R)
- maximum simultaneous open portfolio risk (`MAX_OPEN_RISK_R`, default 4R)
- invalid direction/prices are rejected instead of silently accepted

These controls operate in R units and do not pretend to know the user's account size.

### Deterministic Backtest Lab
`backtest.py` provides a small, dependency-light research engine:
- BUY/SELL TP/SL simulation
- frozen initial risk and R-multiple calculation
- conservative same-candle ambiguity policy (SL wins when both TP and SL are touched)
- callback-based signal backtesting
- explicit warning that lower-timeframe data is required for more precise intrabar ordering

This is a research/backtest component, not a live execution engine.

### Android Companion
The Android app remains intentionally credential-free. It can inspect the public GitHub Actions status and open the repository Actions page. It should never contain Telegram or exchange secrets.

### New GitHub Variables
Optional repository Variables:
- `MAX_DAILY_LOSS_R=3`
- `MAX_OPEN_RISK_R=4`
- `MIN_REWARD_RISK=1.5`

If omitted, safe defaults are used.

### Recommended operating sequence
1. Run static validation and unit tests.
2. Run historical backtests with out-of-sample data.
3. Run paper trading for a meaningful sample.
4. Review expectancy, Profit Factor, Max Drawdown, average R and regime sensitivity.
5. Only then consider any execution layer — isolated, disabled by default, and protected by an explicit paper-trading gate.

## v27.1 — Same-Direction Exposure Guard

`risk_engine.py` gained `same_direction_open_count()` and `can_open_trade()`
now accepts `max_same_direction_open` (new `MAX_SAME_DIRECTION_OPEN`
Variable, default 3). `MAX_OPEN_RISK_R` alone only sums total R across
open trades — it can't tell 4 correlated SELL signals (BTC+ETH+SUI+SOL,
which move together far more often than not) apart from 4 genuinely
independent bets. This closes that gap: once `max_same_direction_open`
positions are open in the same direction, further same-direction signals
are rejected regardless of remaining open-risk budget, while the
opposite direction stays unaffected. 5 new tests cover the count helper,
the rejection case, that the opposite direction isn't blocked, and that
setting it to 0/omitting it disables the guard (backward compatible).
Also reverted `CYCLE_MINUTES`/cron back to 10 minutes (v27.0 defaulted
to 15 assuming a private repo's free-minute budget — this repo is
Public, so that reasoning doesn't apply).

\n## v27.2 — Production Hardening + Research Metrics

- State persistence now fails closed instead of silently swallowing save errors.
- Telegram alerts no longer rely on HTML parsing.
- Added `research.py` with net-R metrics, expectancy, Profit Factor, Max Drawdown,
  and chronological walk-forward split generation.
- Added research tests for costs, drawdown, and walk-forward separation.
- Expanded secret scanning for GitHub PAT and Slack-style token patterns.
- Added `PRODUCTION_RESEARCH_POLICY.md`.
- Added an explicit warning that public repositories should not expose raw trade history.

## v27.2.1 — Fix: v27.2's Telegram Change Broke All Message Formatting

v27.2 replaced `parse_mode: "HTML"` with `html.escape()`-ing the entire
message and dropping parse_mode, reasoning that dynamic content (e.g. an
exception's text) could contain a stray `<`/`>`/`&` and break Telegram's
HTML parser. That risk is real, but the fix as shipped broke all 11+
message templates in main.py that intentionally use `<b>...</b>` for
readable bold headers (signal alerts, trailing-stop notices, the daily
report, crash alerts, risk-rejection notices, etc.) — every one of them
would have rendered as literal `&lt;b&gt;...&lt;/b&gt;` text on the
phone instead of bold, and this wasn't caught by v27.2's own test suite
(no test covered telegram.py's behavior at all).

Fixed properly: `parse_mode: "HTML"` is restored for normal sends, and
if Telegram's own API reports a parse failure (its specific 400 "can't
parse entities" response — the actual failure mode being guarded
against), `send_telegram_alert` now retries that one message as plain
text automatically, so it still gets delivered instead of silently
breaking every message's formatting. New `tests/test_telegram.py` (3
tests, mocked) covers: normal HTML formatting is preserved, the
plain-text fallback fires only on an actual Telegram parse rejection,
and non-parse errors (e.g. rate limiting) retry normally instead of
falling back early.

Also worth flagging from this release (not a bug, a real consideration
raised in `PRODUCTION_RESEARCH_POLICY.md`): if this repository is
Public, `data/history.csv` (committed every cycle) is visible to
anyone — full trade history, symbols, directions, R results. This is
not a secrets leak (no keys/tokens are in it) but is a real strategy/
privacy exposure worth a deliberate decision, not an accident.

## v27.3 — Encrypt Trade History At Rest (data/history.csv.enc)

Closes the privacy gap `PRODUCTION_RESEARCH_POLICY.md` flagged: on a
Public repo (recommended earlier for free unlimited Actions minutes),
`data/history.csv` was committed every cycle in PLAINTEXT — full trade
history (symbols, directions, entry/exit prices, R results) visible to
anyone. Not a secrets leak, but a real strategy/performance exposure.

Fixed by reusing the exact same Fernet key/mechanism as state.json.enc
(`state_manager._get_fernet()`) — no new secret needed. `history.csv` is
now `history.csv.enc`: `append_to_history()` decrypts the existing file
(if any), appends the new row in memory, and re-encrypts the whole
thing (Fernet tokens can't be appended to directly, unlike a plaintext
file — but this file only grows one row per CLOSED trade, so a full
round-trip every append is cheap). Writes are atomic (temp file +
rename), matching the safety pattern state.json.enc already used.

One-time automatic migration: if an old plaintext data/history.csv
exists from before this version, `_read_history_csv()` reads it,
encrypts it into the new file, and deletes the plaintext original — no
manual steps needed. The self-healing repair logic from v25.10 (for a
schema mismatch / malformed row) still works identically, just on the
decrypted CSV text instead of the raw file.

Verified end-to-end through the REAL main.py module (not a standalone
reimplementation) using a fake `ta` stub to work around this sandbox
having no network access to install the real package: legacy-plaintext
migration, confirming the on-disk bytes do NOT contain any plaintext
trade data, appending a new trade, and repairing a corrupted encrypted
file — all through main.py's actual `_read_history_csv` /
`append_to_history` functions. Full test suite re-run with the same
stub: 64/65 tests pass (the one failure is a limitation of the fake
indicator stub returning constant dummy values regardless of input,
unrelated to this change — real `ta` in actual CI will not have this
issue). `.github/workflows/bot.yml` and `.gitignore` updated to match
the new filename; the workflow also stages removal of the old plaintext
file from the repo going forward (it remains in past commits' history —
rotate ENCRYPTION_KEY if that specific past exposure is a concern for
you, since past commits can't be un-published from a public repo without
rewriting git history).


## v27.4 — Closed-candle signal lock

- BUY/SELL analysis excludes the currently-forming final Binance kline on every timeframe.
- TP/SL, trailing and intrabar monitoring continue to use the live 1H candle high/low.
- New entries use the latest live price while direction/indicators come from the last completed 1H candle.
- Added regression tests for live-candle isolation.

## v27.5.1 — Review Pass: Fixed Lint Failure + Restored a Dropped v27.4 Fix

Reviewed the incoming v27.5 package (diffed every file against the
last known-good v27.4 baseline, security-scanned for malicious
patterns — clean, nothing suspicious found) before accepting it.
Two real issues found and fixed:

**1) Lint failure (the reported CI error).** `process_symbol()` assigned
`live_15m`, `live_4h`, and `live_1d` but only ever used `live_1h` — ruff's
F841 correctly failed the build on all 3 unused variables, and since
Lint is a blocking CI gate, EVERY step after it (tests, the actual
trading cycle) was skipped. Fixed by only fetching what's actually used.

**2) Regression: the v27.4 heartbeat reliability fix was silently
dropped.** This v27.5 package appears to have been built from a
pre-v27.4 baseline — `should_skip_cycle_early()` (in main.py) and the
5-minute heartbeat cron (in bot.yml) were both completely absent, along
with their 4 tests in test_main.py. This is the exact fix that was
built in direct response to live reports of the workflow's scheduled
trigger being dropped/delayed by 200+ minutes — restoring it was not
optional. Re-added the function, the cron change, and the tests,
merged cleanly alongside this release's new closed-candle tests.

**Genuinely valuable new content in this release, verified correct:**
- **Closed-candle signal isolation** (`_closed_candles`,
  `prepare_analysis_frames` in main.py): Binance's returned final candle
  is still forming and can change every few seconds — using it for
  DIRECTIONAL analysis meant EMA/MACD/structure/etc. could shift between
  cycles from nothing more than the live candle continuing to move, not
  a real change in market structure. Signal generation now uses only
  completed candles; trade management (SL/TP/trailing touches) still
  correctly uses the live candle so intrabar moves aren't missed. This
  is a plausible real explanation for a reported case of a strong,
  fully-confirmed SELL setup reversing "from the first moment" — worth
  watching whether this reduces that pattern going forward.
- **Fail-closed price-geometry check** (`risk_engine.can_open_trade`):
  rejects any BUY not satisfying SL < Entry < TP, or SELL not satisfying
  TP < Entry < SL, even if the reward:risk ratio alone looks fine —
  guards against an accidental direction/SL/TP inversion upstream.
- **`android-companion/gradle.properties`** (was missing entirely
  before): adds `android.useAndroidX=true` — this specific omission is
  almost certainly what caused the "BUILD FAILED" Gradle error seen
  live, since every dependency in `app/build.gradle.kts` is an AndroidX
  library.

All merged and verified together: 72/73 tests pass against the real
main.py/risk_engine.py (the 1 failure is the same pre-existing,
unrelated limitation of this review environment's `ta`-package
stand-in — confirmed present in every prior review too), static
validator passes, YAML valid.

## v27.6 — Real Backtest Tooling (Not Just the Metrics Library)

v27's `backtest.py`/`research.py` gave the metrics/simulation building
blocks, but there was never an actual runner tying them to real
historical data — this closes that gap with two new scripts and a new
on-demand GitHub Actions workflow so it's runnable from a phone with no
local computer needed:

**`scripts/fetch_historical_klines.py`** — paginated historical OHLCV
downloader (Binance caps each request at 1000 candles; walks the full
requested date range). Deliberately kept separate from
`data_engine.fetch_klines()`, which is optimized for "most recent N
candles right now" (what live cycles need), not paginated historical
ranges. Pagination logic (batch boundaries, no duplicate/missing
candles, graceful termination on total failure instead of an infinite
loop) verified with mocked multi-batch and failure scenarios.

**`scripts/run_backtest.py`** — walk-forward engine that replays
historical data through the SAME production functions the live bot
calls every cycle (`analyze_market`, `is_symbol_on_cooldown`,
`check_trailing_stop`, `check_open_trades`, `update_circuit_breaker`,
`can_open_trade`) rather than reimplementing the logic separately —
so backtest behavior can't silently drift from live behavior over
time. Required a small, safe extension to `trade_monitor.py`: three
functions (`check_open_trades`, `is_symbol_on_cooldown`,
`update_circuit_breaker`) hardcoded `datetime.now(timezone.utc)` for
cooldown/exit timestamps, which would have compared historical
backtest dates against today's real date — breaking cooldown logic
entirely in a backtest. Added an optional `as_of` parameter to all
three (defaults to real now, so live call sites in main.py — which
never pass it — are byte-for-byte unaffected); 2 new tests confirm a
cooldown set for a 2024 date is correctly evaluated against 2024 time,
not today. Verified end-to-end with synthetic data: the no-lookahead
slicing guarantee (a candle can never see data from after its own
close_time), and the full open → trail → close → cooldown lifecycle,
including confirming a second signal attempt is correctly blocked
during an active (historically-dated) cooldown window.

**Known v1 simplifications, disclosed in the script's own docstring:**
MAX_DAILY_LOSS_R isn't enforced (needs cross-symbol daily-loss tracking,
a real feature not yet built); funding rate isn't replayed (no
historical funding data fetched, so funding_score is always 0, same as
whenever it's simply unavailable live); symbols are backtested
independently rather than as one shared portfolio; and cooldown/
circuit-breaker timing is evaluated once per 1H candle rather than the
live bot's exact 10-minute cadence — verified this can shift a
cooldown's expiry by up to one 1H-candle-boundary versus live.

**Honesty note:** every mechanic above was verified in this sandboxed
review environment using synthetic data and mocked network calls (no
real network access here to fetch actual market data) — the walk-
forward and no-lookahead logic itself is solid, but nobody has yet
looked at real output numbers from a real run. Sanity-check the very
first run's trade count and date range before trusting the results.

**Usage** (via the new `.github/workflows/backtest.yml`, manually
triggered from the Actions tab — no local computer needed): set
`symbols` and `days`, run it, then download the `backtest-results`
artifact for `backtest_results.csv` (every simulated trade) and the
console log for the summary (win rate, net R, expectancy, profit
factor, max drawdown, both overall and per-symbol).

## v27.7 — Fix: Adaptive Price Decimal Precision

Confirmed and fixed a real, reported bug: every price field (entry,
SL, TP, ATR, VWAP, exit price) used a fixed `f"{value:,.2f}"` format —
correct for BTC (~117,000.00) but for sub-$1 symbols like DOGEUSDT or
DOTUSDT, entry/SL/TP/ATR/VWAP all rounded to the same value (e.g. all
showing "0.07"), making them visually indistinguishable and hiding real
information (ATR showing "0.00" even at a genuine 0.8% of price).

Added `_decimals_for_reference_price()` + `format_price()`: decimal
count is computed ONCE per message from the signal's own entry price
(not a per-symbol lookup table, which would need maintenance every time
a symbol is added) and applied uniformly to every related number in
that message, so they stay visually consistent. Verified against the
exact reported example values (DOGEUSDT entry 0.07384 / SL 0.07251 /
TP 0.07783 / ATR 0.00121, BTC entry 117,245.30) — all match exactly.
Applied everywhere a price appears: the main signal alert, the risk-
guide trailing-stop preview, both trailing-stop notifications, the SL-
proximity warning, the trade-closed alert, and the daily report's open-
trades list. 4 new tests cover low-price/high-price/zero/invalid-input
cases and the "decimals never decrease as price gets smaller" property.

This was raised as a proposal from a parallel conversation with another
AI tool — reviewed independently, confirmed as a real bug against the
actual codebase (not just taken on claim), implemented directly on this
proven baseline rather than accepting an externally-generated patch, and
verified with tests before being trusted. A second proposal from that
same conversation (re-categorizing the silence-watchdog message's
wording into severity tiers) was NOT applied here — it addresses
message clarity, not the underlying open question of whether the
scheduling gaps are a real GitHub-side issue (independently confirmed
as a currently-worsening, actively-discussed platform problem — see
GitHub Community Discussions #156282, #185355, #201436) or something
specific to this repo's configuration, which still requires seeing the
actual live `bot.yml` content to diagnose with confidence.

## v27.8 — Reviewed an External Proposal Doc: 2 Real Additions, Rest Already Done

A detailed Persian-language proposal document was reviewed point by
point against the ACTUAL current codebase (not taken on claim). Result:
the large majority of it — direction based on multi-timeframe
confluence with an effective NO-TRADE state, R-multiple from frozen
initial_risk, high/low-based TP/SL with conservative same-candle
handling, two-stage trailing, encrypted/atomic/backed-up state, Binance
multi-endpoint fallback, funding rate with Bybit fallback (fail-open),
RR/daily-loss/open-risk/same-direction risk gates, circuit breaker,
symbol cooldown, the v27.5.1 lint fix, and the v27.7 adaptive-decimal
fix — were already implemented and verified in this exact codebase.
Recommended NOT doing the proposed full "7-stage Direction Engine"
restructure: equivalent logic already exists via the weighted
confluence score + ADX/probability/multi-timeframe/15m gates: a full
rewrite would mostly be renaming with real regression risk, not a
material behavior change.

Two genuinely new, valid points were identified and implemented:

**1) Signal reasoning was only ever logged for NO-signal cases (v25.2),
never for a FIRED signal.** analyze_market() now returns a
`score_breakdown` — every non-zero scoring factor (Trend, Momentum,
Structure, VWAP, Funding, Liquidity Sweep, etc.), sorted by magnitude —
and the Telegram alert for every new signal now shows it. Directly
supports the kind of "why did this fire?" question raised by the
DOTUSDT case: the reasoning behind a signal is now visible without
reading logs or code. 3 new tests cover the filter/sort logic (zero-
value factors excluded, sorted by magnitude regardless of sign, all-
zero gives an empty breakdown).

**2) `risk_engine.open_risk_r()` counted a flat 1.0R per open trade,
regardless of state.** A real gap: once trailing moves a trade's SL to
breakeven or into locked-profit territory, that trade can no longer
cost the portfolio anything if stopped out — but it still counted as a
full 1R against the open-risk budget, understating how much headroom
was actually available for new signals. Now computes real remaining
risk from entry to the CURRENT sl (not live price, so no extra lookup
needed) for trades still on the losing side, and correctly floors at
zero (never negative) for trades trailed into profit; fails conservative
(full 1.0R) if entry/sl/direction data is missing, rather than silently
undercounting. 6 new tests cover fresh/breakeven/profit-locked/mixed-
portfolio/SELL-direction/missing-data cases.

**Deprioritized, in agreement with the document's own caution:** Open
Interest and liquidation data — Binance's OI endpoint lives under the
same fapi.binance.com domain already causing funding-rate headaches
from GitHub's IPs, with no obvious equivalent-quality fallback (unlike
funding rate's Bybit fallback); real value is unproven without
backtesting it first. The new backtest lab (v27.6) is the right tool to
actually test whether trailing parameters (0.5R/0.75R) or new
indicators genuinely help, rather than guessing — once real historical
data has been run through it.

## v27.9 — Critical Fix: Backtest Was NOT Actually Portfolio-Aware

The v27.8 backtest result reported to the user (287 trades, win rate
34.1%, Expectancy -0.185R, Profit Factor 0.59) was run against a
methodologically broken tool, exactly as flagged by an independent audit
document reviewed alongside this fix. `run_backtest.py` ran each symbol
completely independently with its own private state — so:

1. **`MAX_CONCURRENT_TRADES` was never checked at all** (this script
   never even imported `has_reached_max_concurrent_trades` — a gap
   found and fixed here, verified with a synthetic 4-symbol test showing
   it previously let all 4 open simultaneously instead of capping at 2).
2. **`MAX_SAME_DIRECTION_OPEN` was only enforced trivially** (a symbol
   can never stack a second trade on itself anyway, so the real
   cross-symbol correlation guard never activated).
3. **`MAX_DAILY_LOSS_R` was hardcoded to 0.0`** — never enforced,
   verified now with a synthetic crash scenario showing new entries are
   correctly blocked portfolio-wide for the rest of the losing day, then
   resume normally the next day.

Rewrote as a true portfolio backtest: every symbol now shares ONE state
dict and ONE unified timeline (union of every symbol's timestamps,
sorted), with real daily-loss tracked from the in-memory closed-trade
list across ALL symbols. All three gates verified with dedicated
synthetic-data tests (4 new tests in `tests/test_run_backtest.py`) — not
just manual spot-checks. Per-trade `score_breakdown` (from v27.8) is now
also saved into `backtest_results.csv` for future analysis (audit
recommendation #2 — log every feature/reason per trade).

**What this means for the -52.98R result already reported:** it is not
trustworthy as-is — trades that should have been blocked by portfolio
risk limits were allowed to open, likely making the reported drawdown
and trade count both larger than they should be. The correct next step
is re-running the backtest with this fixed tool to get a real number,
not reacting to the old one. Whether the underlying signal-generation
logic itself has a genuine edge is still an open, unresolved question —
this fix makes it possible to answer that question accurately, it
doesn't answer it by itself.

**On the audit document's proposed Market Regime Filter / Bull-Bear-
Range classifier:** the critique is credible (trend-following logic
requiring 4H+1D EMA agreement can plausibly perform poorly in ranging or
transitioning markets) but was deliberately NOT implemented yet — it
should be tested as an A/B hypothesis against this now-fixed backtest
tool first, not deployed on faith. Doing so is a reasonable next step
once a trustworthy baseline number exists.
