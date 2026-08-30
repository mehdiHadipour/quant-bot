"""Deterministic OHLC backtest helpers.

This module intentionally does not invent intrabar order. If both SL and TP
are touched by the same candle, the default policy is conservative: SL wins.
Use lower-timeframe data when you need more precise execution ordering.
"""
from dataclasses import dataclass
from typing import Callable, Iterable


@dataclass
class BacktestTrade:
    entry: float
    sl: float
    tp: float
    direction: str
    entry_index: int
    exit_index: int | None = None
    exit_price: float | None = None
    result: str | None = None
    r_multiple: float | None = None


def simulate_trade(candles: Iterable[dict], trade: BacktestTrade,
                   start_index: int = 0, conservative_ambiguity: bool = True):
    initial_risk = abs(trade.entry - trade.sl)
    if initial_risk <= 0:
        raise ValueError("initial risk must be positive")

    for i, candle in enumerate(candles, start=start_index):
        high = float(candle["high"])
        low = float(candle["low"])
        if trade.direction == "BUY":
            hit_sl = low <= trade.sl
            hit_tp = high >= trade.tp
        elif trade.direction == "SELL":
            hit_sl = high >= trade.sl
            hit_tp = low <= trade.tp
        else:
            raise ValueError("direction must be BUY or SELL")

        if not (hit_sl or hit_tp):
            continue

        if hit_sl and hit_tp and conservative_ambiguity:
            hit = "SL"
        else:
            hit = "SL" if hit_sl else "TP"

        trade.exit_index = i
        trade.result = "LOSS" if hit == "SL" else "WIN"
        trade.exit_price = trade.sl if hit == "SL" else trade.tp
        if trade.direction == "BUY":
            trade.r_multiple = (trade.exit_price - trade.entry) / initial_risk
        else:
            trade.r_multiple = (trade.entry - trade.exit_price) / initial_risk
        return trade

    return trade


def run_signal_backtest(candles, signal_fn: Callable[[int, object], dict | None]):
    """Run a simple signal callback over candles.

    signal_fn(index, candles_so_far) returns:
      {"direction": "BUY"/"SELL", "entry": ..., "sl": ..., "tp": ...}
    Only one position is held at a time. This is a research tool, not a
    production execution engine.
    """
    results = []
    i = 0
    while i < len(candles):
        signal = signal_fn(i, candles[: i + 1])
        if not signal:
            i += 1
            continue
        trade = BacktestTrade(
            entry=float(signal["entry"]),
            sl=float(signal["sl"]),
            tp=float(signal["tp"]),
            direction=signal["direction"],
            entry_index=i,
        )
        closed = simulate_trade(candles[i + 1:], trade, start_index=i + 1)
        if closed.exit_index is None:
            break
        results.append(closed)
        i = closed.exit_index + 1
    return results
