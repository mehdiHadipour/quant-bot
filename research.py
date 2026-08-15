"""Research-grade backtest metrics and chronological walk-forward helpers."""
from __future__ import annotations

import random
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


@dataclass(frozen=True)
class MonteCarloResult:
    n_simulations: int
    n_trades_per_sim: int
    median_max_drawdown_r: float
    p95_max_drawdown_r: float
    worst_max_drawdown_r: float
    probability_of_ruin: float
    median_final_equity_r: float
    p05_final_equity_r: float


def monte_carlo_bootstrap(
    r_multiples: Iterable[float],
    *,
    n_simulations: int = 2000,
    ruin_threshold_r: float = -10.0,
    seed: int | None = None,
) -> MonteCarloResult:
    """Reshuffle the ORDER of already-closed trades' R-multiples many
    times (sampling with replacement) to see how much of a backtest's
    apparent drawdown/equity curve is a property of the strategy versus
    a property of the specific sequence those trades happened to occur
    in. A single backtest run shows exactly one path through history;
    real trading will not replay that exact path even if the strategy's
    per-trade edge is identical, so a single equity curve alone
    understates real drawdown risk.

    Deliberately simple and dependency-free (Python's own `random`, no
    numpy) so it stays easy to audit and unit-test. This is NOT a
    forecast of future returns — the input R-multiples still come from
    one historical sample and share whatever regime bias that sample
    has; it only answers "given that this set of trade outcomes is
    representative, how much does trade ORDER alone affect the worst
    case?"

    ruin_threshold_r: a portfolio-level drawdown (in cumulative R) past
    which a run counts as "ruin" for probability_of_ruin — default -10R
    is a rough, configurable stand-in for "lost an unrecoverable amount
    of the account"; callers should pick a value that matches their own
    real MAX_DAILY_LOSS_R/MAX_OPEN_RISK_R risk budget instead of relying
    on this default for real capital decisions.
    """
    trades = [float(x) for x in r_multiples]
    if not trades:
        return MonteCarloResult(
            n_simulations=0, n_trades_per_sim=0,
            median_max_drawdown_r=0.0, p95_max_drawdown_r=0.0,
            worst_max_drawdown_r=0.0, probability_of_ruin=0.0,
            median_final_equity_r=0.0, p05_final_equity_r=0.0,
        )

    rng = random.Random(seed)
    n = len(trades)
    max_drawdowns = []
    final_equities = []
    ruin_count = 0

    for _ in range(n_simulations):
        equity = peak = max_dd = 0.0
        for _ in range(n):
            equity += trades[rng.randrange(n)]
            peak = max(peak, equity)
            max_dd = max(max_dd, peak - equity)
            if equity <= ruin_threshold_r:
                ruin_count += 1
                break
        max_drawdowns.append(max_dd)
        final_equities.append(equity)

    max_drawdowns.sort()
    final_equities.sort()

    def _percentile(sorted_values, pct):
        if not sorted_values:
            return 0.0
        idx = min(len(sorted_values) - 1, max(0, int(round(pct / 100 * (len(sorted_values) - 1)))))
        return sorted_values[idx]

    return MonteCarloResult(
        n_simulations=n_simulations,
        n_trades_per_sim=n,
        median_max_drawdown_r=_percentile(max_drawdowns, 50),
        p95_max_drawdown_r=_percentile(max_drawdowns, 95),
        worst_max_drawdown_r=max_drawdowns[-1],
        probability_of_ruin=ruin_count / n_simulations,
        median_final_equity_r=_percentile(final_equities, 50),
        p05_final_equity_r=_percentile(final_equities, 5),
    )


def walk_forward_fold_metrics(
    trades_with_index: list[tuple[int, float]],
    splits: list[tuple[range, range]],
    *,
    fee_r_per_trade: float = 0.0,
    slippage_r_per_trade: float = 0.0,
) -> list[BacktestMetrics]:
    """Apply walk_forward_splits' fold boundaries to a list of
    (chronological_index, r_multiple) pairs and summarize each fold's
    OUT-OF-SAMPLE (test) window only — the piece walk_forward_splits
    itself deliberately leaves to the caller, since it only computes
    index ranges and has no opinion on what a "trade" or "metric" is.

    `trades_with_index` lets a caller map real trades (which don't
    arrive one-per-candle) onto the candle-index folds returned by
    walk_forward_splits: pass (candle_index_at_entry, r_multiple) for
    every closed trade. Folds with zero trades in their test window
    return a BacktestMetrics with trades=0 rather than being skipped, so
    a caller can see WHERE the strategy went quiet, not just silently
    lose that fold from the report.
    """
    results = []
    for _train_range, test_range in splits:
        test_start, test_stop = test_range.start, test_range.stop
        fold_r = [r for idx, r in trades_with_index if test_start <= idx < test_stop]
        results.append(summarize_r_multiples(
            fold_r, fee_r_per_trade=fee_r_per_trade, slippage_r_per_trade=slippage_r_per_trade
        ))
    return results
