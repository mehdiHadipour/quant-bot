# V30.4 Root-Cause & Validation Report

## Finding
The 96/1 SELL/BUY imbalance in V30.2 is not caused by an asymmetric BUY/SELL formula. Raw sweep, MSS and FVG counts are broadly symmetric. The main bottleneck is the hard requirement that 4H and 1D EMA(50/200) biases agree. On the supplied period, the 1D EMA50/200 state is overwhelmingly bearish for most symbols, so bullish setups are filtered out before scoring.

## What was tested
- Original hard 4H=1D gate: 97 trades, -7R.
- 4H-primary/soft daily context + Asia: worse (-19R at score 70; -13R at 75). Rejected.
- 4H-primary without daily gate + Asia: worse (-25R at score 70). Rejected.
- Alternative daily EMA20/50 and close-vs-EMA200 regimes: did not improve the sample. Rejected.
- Lower confluence threshold with the original validated structure: 65 produced the best net result among tested 65/70/75/80 thresholds: -3R.

## Important conclusion
The directional imbalance is primarily a market-regime/data-period effect amplified by the HTF gate, not evidence that the SELL formula is mathematically broken. V30.4 therefore does not artificially force equal BUY/SELL counts. It keeps the validated HTF gate, enables Asia, and uses the best tested threshold of 65 on this dataset.

## Data integrity
No synthetic news, order-book depth or true footprint data are invented. Footprint and Hyper-Liquidity remain explicitly OHLCV/taker-buy proxies unless real historical tick/order-book data are supplied.
