import unittest
from research import summarize_r_multiples, walk_forward_splits


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
