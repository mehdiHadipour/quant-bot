#!/usr/bin/env python3
"""
🚀 AI Quant Bot v12.3 - Ultimate Serverless Edition
Modular execution with GitHub Actions
"""

from datetime import datetime, timezone
import pandas as pd
import os
import sys

from config import SYMBOLS
from data_engine import fetch_klines
from indicators import analyze_market
from trade_monitor import check_open_trades, update_circuit_breaker
from state_manager import load_state, save_state
from telegram import send_telegram_alert

HISTORY_FILE = "data/history.csv"


def append_to_history(trade):
    """Append a closed trade to the history CSV."""
    os.makedirs("data", exist_ok=True)
    df = pd.DataFrame([trade])
    if not os.path.exists(HISTORY_FILE):
        df.to_csv(HISTORY_FILE, index=False)
    else:
        df.to_csv(HISTORY_FILE, mode="a", header=False, index=False)


def process_symbol(state, symbol):
    print(f"📊 Analyzing {symbol}...")
    df_1h = fetch_klines(symbol, "1h")
    df_4h = fetch_klines(symbol, "4h")

    if df_1h is None or df_4h is None or df_1h.empty or df_4h.empty:
        print(f"⚠️ Skipping {symbol}: no market data available.")
        return

    current_price = df_1h["close"].iloc[-1]
    closed_trades = check_open_trades(state, current_price, symbol)

    if closed_trades:
        update_circuit_breaker(state, closed_trades)
        for trade in closed_trades:
            append_to_history(trade)
            emoji = "✅" if trade["result"] == "WIN" else "❌"
            send_telegram_alert(
                f"{emoji} <b>معامله بسته شد</b> - {symbol}\n"
                f"نتیجه: {trade['result']}\n"
                f"ورود: {trade['entry']:,.2f}\n"
                f"خروج: {trade['exit_price']:,.2f}"
            )
        save_state(state)
        return

    result = analyze_market(df_1h, df_4h, symbol)
    if not result:
        return

    atr = result["atr"]
    direction = result["direction"]
    price = result["price"]

    sl = price - (atr * 1.5) if direction == "BUY" else price + (atr * 1.5)
    tp = price + (atr * 3.0) if direction == "BUY" else price - (atr * 3.0)

    msg = f"""
🚨 <b>سیگنال جدید</b> - {result['symbol']}
📊 جهت: {direction}
📈 احتمال BUY: {result['buy']:.1f}%
📉 احتمال SELL: {result['sell']:.1f}%
💰 قیمت ورود: {price:,.2f}
🛑 SL: {sl:,.2f}
🎯 TP: {tp:,.2f}
⚠️ ATR: {atr:,.2f} ({(atr / price * 100):.2f}%)
"""
    print(msg)
    send_telegram_alert(msg)

    state["trades"].append({
        "symbol": result["symbol"],
        "direction": direction,
        "entry": price,
        "tp": tp,
        "sl": sl,
        "status": "open",
        "time": datetime.now(timezone.utc).isoformat(),
    })
    save_state(state)


def main():
    print(f"🚀 Starting cycle - {datetime.now(timezone.utc).isoformat()}")
    
    # 1. ارسال پیام تست هنگام اولین اجرا برای اطمینان از اتصال تلگرام
    send_telegram_alert("✅ ربات معاملاتی شما با موفقیت راه‌اندازی شد و در حال آماده‌به‌کار است!")

    state = load_state()

    if state.get("circuit_breaker"):
        cb_time = datetime.fromisoformat(state["circuit_breaker"])
        if datetime.now(timezone.utc) < cb_time:
            print(f"🛑 Circuit breaker active until {state['circuit_breaker']}")
            return
        else:
            print("✅ Circuit breaker expired. Resetting.")
            state["circuit_breaker"] = None
            state["stats"]["streak"] = 0
            save_state(state)

    for symbol in SYMBOLS:
        try:
            process_symbol(state, symbol)
        except Exception as e:
            print(f"❌ Error processing {symbol}: {e}")

    print("✅ Cycle completed.")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"❌ Fatal error: {e}", file=sys.stderr)
        try:
            send_telegram_alert(f"❌ <b>خطای اجرای ربات</b>\n{e}")
        except Exception:
            pass
        sys.exit(1)
