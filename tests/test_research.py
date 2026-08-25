import unittest
from research import (
    summarize_r_multiples, walk_forward_splits, walk_forward_fold_metrics,
    monte_carlo_bootstrap,
)


class TestResearchMetrics(unittest.TestCase):
    def test_costs_reduce_net_r_and_expectancy(self):
        m = summarize_r_multiples(
            [2.0, -1.0, 1.0],
            fee_r_per_trade=0.1,
            slippage_r_per_trade=0.1,
        )
        self.assertEqual(m.trades, 3)
        self.assertAlmostEqual(m.net_r, 1.4)
        self.assertAlmostEqual(m.expectancy_r, 1.4 / 3)

    def test_drawdown_is_calculated_from_equity_curve(self):
        m = summarize_r_multiples([2.0, -3.0, 1.0])
        self.assertAlmostEqual(m.max_drawdown_r, 3.0)

    def test_walk_forward_test_is_strictly_after_train(self):
        splits = walk_forward_splits(100, train_size=40, test_size=20)
        self.assertTrue(splits)
        for train, test in splits:
            self.assertLess(max(train), min(test))

    def test_invalid_sizes_fail(self):
        with self.assertRaises(ValueError):
            walk_forward_splits(100, train_size=0, test_size=20)


class TestWalkForwardFoldMetrics(unittest.TestCase):
    def test_each_fold_summarizes_only_its_own_test_window(self):
        # 4 candle-indexed trades: two in [0,20) fold's test window (say
        # test range 10-20), two in the next fold's test window (30-40).
        splits = [
            (range(0, 10), range(10, 20)),
            (range(20, 30), range(30, 40)),
        ]
        trades_with_index = [(12, 1.0), (15, -0.5), (32, 2.0), (35, -1.0)]
        results = walk_forward_fold_metrics(trades_with_index, splits)
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0].trades, 2)
        self.assertAlmostEqual(results[0].net_r, 0.5)
        self.assertEqual(results[1].trades, 2)
        self.assertAlmostEqual(results[1].net_r, 1.0)

    def test_fold_with_no_trades_reports_zero_not_skipped(self):
        splits = [(range(0, 10), range(10, 20))]
        results = walk_forward_fold_metrics([(999, 1.0)], splits)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].trades, 0)

    def test_costs_applied_per_fold(self):
        splits = [(range(0, 10), range(10, 20))]
        trades_with_index = [(12, 1.0), (15, 1.0)]
        results = walk_forward_fold_metrics(trades_with_index, splits, fee_r_per_trade=0.1)
        self.assertAlmostEqual(results[0].net_r, 1.8)


class TestMonteCarloBootstrap(unittest.TestCase):
    def test_empty_input_returns_zeroed_result(self):
        result = monte_carlo_bootstrap([], n_simulations=100)
        self.assertEqual(result.n_simulations, 0)
        self.assertEqual(result.median_max_drawdown_r, 0.0)
        self.assertEqual(result.probability_of_ruin, 0.0)

    def test_all_winning_trades_never_draws_down_or_ruins(self):
        result = monte_carlo_bootstrap([1.0, 2.0, 1.5], n_simulations=200, seed=42)
        self.assertEqual(result.median_max_drawdown_r, 0.0)
        self.assertEqual(result.probability_of_ruin, 0.0)
        self.assertGreater(result.median_final_equity_r, 0.0)

    def test_deep_losses_trigger_ruin_probability(self):
        result = monte_carlo_bootstrap(
            [-5.0, -5.0, -5.0], n_simulations=200, ruin_threshold_r=-10.0, seed=42
        )
        self.assertGreater(result.probability_of_ruin, 0.5)

    def test_same_seed_is_reproducible(self):
        r1 = monte_carlo_bootstrap([1.0, -1.0, 2.0, -0.5], n_simulations=300, seed=7)
        r2 = monte_carlo_bootstrap([1.0, -1.0, 2.0, -0.5], n_simulations=300, seed=7)
        self.assertEqual(r1, r2)

    def test_result_trade_count_matches_input(self):
        result = monte_carlo_bootstrap([1.0, -1.0, 2.0], n_simulations=50, seed=1)
        self.assertEqual(result.n_trades_per_sim, 3)
        self.assertEqual(result.n_simulations, 50)
