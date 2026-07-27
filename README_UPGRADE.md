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
