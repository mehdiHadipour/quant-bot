#!/usr/bin/env python3
"""
Robustness validation on top of an existing backtest run.

Two things this adds that scripts/run_backtest.py's single headline
numbers cannot show on their own:

1. Walk-forward fold consistency: splits the trade sequence into
   rolling chronological folds (research.walk_forward_splits +
   walk_forward_fold_metrics) and reports each fold's win rate/
   expectancy separately. A strategy whose edge is real and durable
   should look broadly similar fold-to-fold; one where all the profit
   came from a single fold (a single regime/event) is a real overfitting
   red flag that a single full-period headline number hides.

2. Monte Carlo trade-order bootstrap (research.monte_carlo_bootstrap):
   reshuffles the SAME closed trades' R-multiples thousands of times to
   show a distribution of possible max-drawdown/final-equity outcomes,
   not just the one sequence that happened to occur historically.

REQUIRES: scripts/run_backtest.py has already been run and produced
backtest_data/backtest_results.csv (or pass a different --input).

USAGE:
    python scripts/validate_robustness.py --input backtest_data/backtest_results.csv
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd

from research import walk_forward_splits, walk_forward_fold_metrics, monte_carlo_bootstrap


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--input", default="backtest_data/backtest_results.csv",
                         help="CSV produced by scripts/run_backtest.py (needs an r_multiple column; "
                              "exit_time is used to sort chronologically if present).")
    parser.add_argument("--n-folds", type=int, default=5,
                         help="Approximate number of walk-forward folds to report (default: 5).")
    parser.add_argument("--min-fold-trades", type=int, default=1,
                         help="Minimum trades a fold must contain to be sized meaningfully (default: 1); "
                              "used only to pick fold size, not to drop folds from the report.")
    parser.add_argument("--n-simulations", type=int, default=2000,
                         help="Monte Carlo simulation count (default: 2000).")
    parser.add_argument("--ruin-threshold-r", type=float, default=-10.0,
                         help="Cumulative R drawdown counted as 'ruin' for probability_of_ruin "
                              "(default: -10.0 — pick a value matching your real risk budget).")
    parser.add_argument("--fee-r", type=float, default=0.02)
    parser.add_argument("--slippage-r", type=float, default=0.02)
    parser.add_argument("--seed", type=int, default=None, help="Optional RNG seed for reproducible output.")
    args = parser.parse_args()

    if not os.path.exists(args.input):
        print(f"❌ {args.input} not found. Run scripts/run_backtest.py first.")
        sys.exit(1)

    df = pd.read_csv(args.input)
    if "r_multiple" not in df.columns or df.empty:
        print(f"❌ {args.input} has no r_multiple data to analyze.")
        sys.exit(1)

    if "exit_time" in df.columns:
        try:
            df = df.assign(_sort_key=pd.to_datetime(df["exit_time"], errors="coerce", utc=True))
            df = df.sort_values("_sort_key").reset_index(drop=True)
        except Exception:
            pass

    r_multiples = [float(x) for x in df["r_multiple"]]
    n = len(r_multiples)

    print(f"\n{'=' * 55}")
    print(f"تحلیل استحکام (Robustness) روی {n} معاملهٔ بسته‌شده")
    print(f"{'=' * 55}")

    # --- 1) Walk-forward fold consistency ---
    fold_size = max(args.min_fold_trades, n // max(args.n_folds, 1))
    if fold_size <= 0 or n < fold_size * 2:
        print(f"\n⚠️ دادهٔ کافی برای {args.n_folds} دورهٔ Walk-Forward وجود ندارد "
              f"({n} معامله؛ حداقل لازم تقریبی: {fold_size * 2}). این بخش رد شد.")
    else:
        splits = walk_forward_splits(n, train_size=fold_size, test_size=fold_size, step_size=fold_size)
        trades_with_index = list(enumerate(r_multiples))
        fold_metrics = walk_forward_fold_metrics(
            trades_with_index, splits, fee_r_per_trade=args.fee_r, slippage_r_per_trade=args.slippage_r
        )
        print(f"\n--- ثبات عملکرد در {len(fold_metrics)} دورهٔ زمانی متوالی (هر کدام ~{fold_size} معامله) ---")
        print("اگر یک یا دو دوره کل سود را تولید کرده‌اند و بقیه ضعیف/منفی‌اند، این نشانهٔ overfitting "
              "روی یک رژیم خاص بازار است، نه یک مزیت پایدار.")
        for i, m in enumerate(fold_metrics, start=1):
            if m.trades == 0:
                print(f"  دورهٔ {i}: معامله‌ای در این بازه نبود")
                continue
            print(f"  دورهٔ {i}: {m.trades} معامله | نرخ برد {m.win_rate:.1f}% | "
                  f"Expectancy {m.expectancy_r:+.3f}R | Max DD {m.max_drawdown_r:.2f}R")

    # --- 2) Monte Carlo trade-order bootstrap ---
    mc = monte_carlo_bootstrap(
        r_multiples, n_simulations=args.n_simulations,
        ruin_threshold_r=args.ruin_threshold_r, seed=args.seed,
    )
    print(f"\n--- Monte Carlo Bootstrap ({mc.n_simulations} شبیه‌سازی، با تعویض ترتیب معاملات) ---")
    print("همان معاملات واقعی را با ترتیب‌های تصادفی مختلف بازآرایی می‌کند تا نشان دهد چقدر از "
          "نمودار equity یک بک‌تست به‌خاطر ترتیب خاص وقایع تاریخی است، نه خودِ استراتژی.")
    print(f"  حداکثر افت سرمایه (Drawdown) میانه: {mc.median_max_drawdown_r:.2f}R")
    print(f"  حداکثر افت سرمایه در بدترین ۵٪ حالت‌ها (P95): {mc.p95_max_drawdown_r:.2f}R")
    print(f"  بدترین افت سرمایهٔ مشاهده‌شده در کل شبیه‌سازی‌ها: {mc.worst_max_drawdown_r:.2f}R")
    print(f"  equity نهایی میانه: {mc.median_final_equity_r:+.2f}R")
    print(f"  equity نهایی در بدترین ۵٪ حالت‌ها (P05): {mc.p05_final_equity_r:+.2f}R")
    print(f"  احتمال رسیدن به آستانهٔ 'نابودی' ({args.ruin_threshold_r:.1f}R): {mc.probability_of_ruin:.1%}")
    print(
        "\nℹ️ این یک پیش‌بینی آینده نیست — همچنان از همان نمونهٔ تاریخی معاملات استفاده می‌کند و هر بایاس "
        "رژیم بازار در آن دادهٔ اصلی را به ارث می‌برد. فقط ریسک 'ترتیب شانسی معاملات' را جدا می‌کند."
    )


if __name__ == "__main__":
    main()
