"""Research-grade backtest metrics and chronological walk-forward helpers."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class BacktestMetrics:
    trades: int
    wins: int
    losses: int
    win_rate: float
    net_r: float
    expectancy_r: float
    profit_factor: float
    max_drawdown_r: float
    gross_profit_r: float
    gross_loss_r: float


def summarize_r_multiples(
    r_multiples: Iterable[float],
    *,
    fee_r_per_trade: float = 0.0,
    slippage_r_per_trade: float = 0.0,
) -> BacktestMetrics:
    """Summarize closed trades after fixed per-trade costs expressed in R."""
    raw = [float(x) for x in r_multiples]
    cost = float(fee_r_per_trade) + float(slippage_r_per_trade)
    net = [x - cost for x in raw]

    wins = sum(x > 0 for x in net)
    losses = sum(x <= 0 for x in net)
    gross_profit = sum(x for x in net if x > 0)
    gross_loss = abs(sum(x for x in net if x < 0))

    equity = peak = max_dd = 0.0
    for x in net:
        equity += x
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)

    if gross_loss > 0:
        profit_factor = gross_profit / gross_loss
    elif gross_profit > 0:
        profit_factor = float("inf")
    else:
        profit_factor = 0.0

    return BacktestMetrics(
        trades=len(net),
        wins=wins,
        losses=losses,
        win_rate=(wins / len(net) * 100) if net else 0.0,
        net_r=sum(net),
        expectancy_r=(sum(net) / len(net)) if net else 0.0,
        profit_factor=profit_factor,
        max_drawdown_r=max_dd,
        gross_profit_r=gross_profit,
        gross_loss_r=gross_loss,
    )


def walk_forward_splits(
    n_samples: int,
    *,
    train_size: int,
    test_size: int,
    step_size: int | None = None,
) -> list[tuple[range, range]]:
    """Create chronological train/test windows with strict no-look-ahead."""
    if n_samples < 0 or train_size <= 0 or test_size <= 0:
        raise ValueError("n_samples must be >= 0 and train/test sizes must be positive")
    step = step_size or test_size
    if step <= 0:
        raise ValueError("step_size must be positive")

    splits = []
    start = 0
    while start + train_size + test_size <= n_samples:
        splits.append((
            range(start, start + train_size),
            range(start + train_size, start + train_size + test_size),
        ))
        start += step
    return splits
