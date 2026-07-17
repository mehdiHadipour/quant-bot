#!/usr/bin/env python3
"""
🚀 AI Quant Bot v21.0 - State Persistence Fix (Critical)
Fixes a critical git-add bug that silently discarded every state save
since day one (a single `git add a b c` call failed atomically whenever
any of the three paths didn't exist yet, which was almost always true
for data/history.csv before the first trade ever closed). Every run was
therefore starting from a blank state, causing daily reports to repeat
and undermining trade tracking, SL warnings, and cooldowns. Also includes
the v20 SELL-signal-symmetry fix and all earlier features unchanged.
"""

from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed
import pandas as pd
import os
import sys

from config import SYMBOLS, ATR_SL_MULTIPLIER, ATR_TP_MULTIPLIER, RISK_PERCENT_PER_TRADE
from data_engine import fetch_klines
from indicators import analyze_market
from trade_monitor import (
    check_open_trades,
    check_sl_warnings,
    is_symbol_on_cooldown,
    update_circuit_breaker,
)
from state_manager import load_state, save_state
from telegram import send_telegram_alert
from logger import log

HISTORY_FILE = "data/history.csv"

# Timeframes fetched for every symbol each cycle:
#   15m — short-term momentum confirmation (final entry-timing gate)
#   1h  — primary indicator/entry timeframe (unchanged core logic)
#   4h  — trend bias
#   1d  — higher-timeframe trend agreement (confluence gate)
INTERVALS = ["15m", "1h", "4h", "1d"]

# If every single symbol fails to fetch data for this many consecutive
# cycles (15 min each), something is systemically wrong (network, Binance
# fully blocked, etc.) rather than a one-off blip — worth a one-time alert.
FETCH_FAILURE_ALERT_THRESHOLD = 4


def append_to_history(trade):
    """Append a closed trade to the history CSV."""
    os.makedirs("data", exist_ok=True)
    df = pd.DataFrame([trade])
    if not os.path.exists(HISTORY_FILE):
        df.to_csv(HISTORY_FILE, index=False)
    else:
        df.to_csv(HISTORY_FILE, mode="a", header=False, index=False)


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
                jobs[executor.submit(fetch_klines, symbol, interval)] = (symbol, interval)

        for future in as_completed(jobs):
            symbol, interval = jobs[future]
            try:
                results[symbol][interval] = future.result()
            except Exception as e:
                log.error(f"Error fetching {symbol} {interval}: {e}")
                results[symbol][interval] = None

    return results


def build_risk_tip(direction, price, sl, tp):
    """Purely informational trailing-stop / position-sizing guidance.
    The bot does not place or size any real order — this is just text
    to help the person manage the trade manually."""
    risk_per_unit = abs(price - sl)
    halfway = price + (tp - price) / 2 if direction == "BUY" else price - (price - tp) / 2
    return (
        f"\n💡 <b>راهنمای مدیریت ریسک</b> (فقط پیشنهادی):\n"
        f"• اندازهٔ پوزیشن برای ریسک {RISK_PERCENT_PER_TRADE:.1f}٪ سرمایه:\n"
        f"  (سرمایهٔ شما × {RISK_PERCENT_PER_TRADE:.1f}٪) ÷ {risk_per_unit:,.2f}\n"
        f"• Trailing: وقتی قیمت به {halfway:,.2f} رسید (نیمهٔ راه تا TP)، "
        f"SL را به نقطهٔ ورود ({price:,.2f}) منتقل کنید تا معامله بدون ریسک شود."
    )


def process_symbol(state, symbol, klines_for_symbol, counters):
    log.info(f"📊 Analyzing {symbol}...")

    df_15m = klines_for_symbol.get("15m")
    df_1h = klines_for_symbol.get("1h")
    df_4h = klines_for_symbol.get("4h")
    df_1d = klines_for_symbol.get("1d")

    # NOTE: these are pandas DataFrames or None.
    # Never use `not df` on a DataFrame — its truth value is ambiguous
    # and raises a ValueError. Always compare explicitly to None.
    if df_1h is None or df_4h is None or df_1h.empty or df_4h.empty:
        log.warning(f"Skipping {symbol}: no 1h/4h market data available.")
        return

    counters["fetched_ok"] += 1
    current_price = df_1h["close"].iloc[-1]

    # One-time warning if any open trade on this symbol has drifted close
    # to its stop-loss, so the person can react before it actually triggers.
    sl_warnings = check_sl_warnings(state, current_price, symbol)
    if sl_warnings:
        for trade in sl_warnings:
            send_telegram_alert(
                f"⚠️ <b>هشدار نزدیک‌شدن به SL</b> - {symbol}\n"
                f"جهت: {trade['direction']}\n"
                f"قیمت ورود: {trade['entry']:,.2f}\n"
                f"قیمت فعلی: {current_price:,.2f}\n"
                f"حد ضرر (SL): {trade['sl']:,.2f}\n"
                f"قیمت به نزدیکی حد ضرر رسیده — مراقب باشید."
            )
        save_state(state)

    closed_trades = check_open_trades(state, current_price, symbol)

    if closed_trades:
        update_circuit_breaker(state, closed_trades)
        for trade in closed_trades:
            append_to_history(trade)
            counters["closed"] += 1
            emoji = "✅" if trade["result"] == "WIN" else "❌"
            r = trade.get("r_multiple", 0.0)
            send_telegram_alert(
                f"{emoji} <b>معامله بسته شد</b> - {symbol}\n"
                f"نتیجه: {trade['result']} ({r:+.2f}R)\n"
                f"ورود: {trade['entry']:,.2f}\n"
                f"خروج: {trade['exit_price']:,.2f}"
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

    # 15m and 1D are used as confluence gates inside analyze_market; if they
    # failed to fetch this cycle, fall back to an empty frame so the
    # relevant checks are skipped gracefully rather than crashing (the 1H/4H
    # core logic — the part that matters most — still runs normally).
    safe_15m = df_15m if df_15m is not None else pd.DataFrame(columns=df_1h.columns)
    safe_1d = df_1d if df_1d is not None else pd.DataFrame(columns=df_1h.columns)

    result = analyze_market(safe_15m, df_1h, df_4h, safe_1d, symbol)
    if not result:
        return

    atr = result["atr"]
    direction = result["direction"]
    price = result["price"]

    sl = price - (atr * ATR_SL_MULTIPLIER) if direction == "BUY" else price + (atr * ATR_SL_MULTIPLIER)
    tp = price + (atr * ATR_TP_MULTIPLIER) if direction == "BUY" else price - (atr * ATR_TP_MULTIPLIER)

    msg = f"""
🚨 <b>سیگنال جدید</b> - {result['symbol']}
📊 جهت: {direction}
📈 احتمال BUY: {result['buy']:.1f}%
📉 احتمال SELL: {result['sell']:.1f}%
💰 قیمت ورود: {price:,.2f}
🛑 SL: {sl:,.2f}
🎯 TP: {tp:,.2f}
⚠️ ATR: {atr:,.2f} ({(atr / price * 100):.2f}%)
📶 ADX: {result.get('adx', 0):.1f}
🧭 تأیید چندتایم‌فریمی: 15m + 1H + 4H + 1D هم‌جهت
"""

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
        "status": "open",
        "sl_warning_sent": False,
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
    if not os.path.exists(HISTORY_FILE):
        return None
    try:
        df = pd.read_csv(HISTORY_FILE)
    except Exception as e:
        log.warning(f"Could not read history.csv for performance ratios: {e}")
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
            f"  • {t['symbol']} {t['direction']} — ورود: {t['entry']:,.2f}"
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


def main():
    log.info(f"🚀 Starting cycle - {datetime.now(timezone.utc).isoformat()}")
    state = load_state()

    if state.get("circuit_breaker"):
        cb_time = datetime.fromisoformat(state["circuit_breaker"])
        if datetime.now(timezone.utc) < cb_time:
            log.warning(f"🛑 Circuit breaker active until {state['circuit_breaker']}")
            return
        else:
            log.info("✅ Circuit breaker expired. Resetting.")
            state["circuit_breaker"] = None
            state["stats"]["streak"] = 0
            save_state(state)

    maybe_send_daily_report(state)

    counters = {"signals": 0, "closed": 0, "fetched_ok": 0}
    klines = fetch_all_klines(SYMBOLS)

    for symbol in SYMBOLS:
        try:
            process_symbol(state, symbol, klines[symbol], counters)
        except Exception as e:
            # One bad symbol should never take down the whole cycle.
            log.error(f"Error processing {symbol}: {e}")

    check_fetch_health(state, counters["fetched_ok"], len(SYMBOLS))
    save_state(state)

    log.info(
        f"✅ Cycle completed. سیگنال‌های جدید: {counters['signals']} | "
        f"معاملات بسته‌شده: {counters['closed']} | نمادهای موفق: {counters['fetched_ok']}/{len(SYMBOLS)}"
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log.error(f"Fatal error: {e}")
        try:
            send_telegram_alert(f"❌ <b>خطای اجرای ربات</b>\n{e}")
        except Exception:
            pass
        sys.exit(1)
