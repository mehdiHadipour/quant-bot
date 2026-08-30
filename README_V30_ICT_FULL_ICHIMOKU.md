# Quant Bot V30 — ICT Full + Ichimoku

V30 extends V29 with a leakage-safe Ichimoku layer and a compact parameter-selection process.

## Active modules
- ICT: HTF 4H/1D bias, liquidity, premium/discount, sweep, displacement, MSS, FVG, OB/BPR proxies, PO3/session context.
- Order-flow/footprint proxy: taker-buy delta and cumulative delta.
- Hyper-Liquidity proxy: volume/ATR/depth proxy; no fake order book data.
- Fundamental/news: live module remains available; historical backtest is neutral unless timestamped news sidecar is supplied.
- Session hard gate: London/New York only, DST-aware; overlap gets highest score.
- Ichimoku: Tenkan/Kijun/Senkou B + 26-bar displacement, current cloud, forward cloud, Chikou confirmation.

## Ichimoku default
9/26/52 remains the primary configuration. Research sources note 9/26/52 as the classic baseline; 10/30/60 is a common crypto adaptation, but there is no universal optimum and parameters should be validated rather than assumed optimal.

## Parameter selection
`optimize_v30.py` searches a compact grid of 3 Ichimoku presets, ATR 14/20, displacement threshold 0.65/0.85/1.0, and score threshold 65/70/75. The first 70% of each symbol is used for selection and the last 30% is held out. This is intended to reduce curve fitting.

## Backtest
Put the supplied historical CSVs in `backtest_data/` and run:
`python ict_full_backtest.py`

For parameter research:
`python optimize_v30.py`

## Selected V30 production research parameters
- Ichimoku: 9 / 26 / 52
- ATR: 14
- Displacement quality threshold: 0.85 ATR
- Final confluence score: 70

These are the best risk-aware settings among the compact configurations actually tested on the supplied dataset. They are not claimed to be globally optimal.


## V30.2 Fibonacci layer
- Fibonacci is enabled in both live signal scoring and the deterministic backtest.
- Completed 50-bar dealing range only; no future bars are used.
- Preferred retracement zone: 50%-78.6%.
- OTE sub-zone: 61.8%-78.6%.
- Score: +10/-10 in OTE, +4/-4 in the 50%-61.8% middle zone, directionally aligned with the market bias.
- Fibonacci is a confirmation/location vote, not a standalone entry trigger.
- Backtest result on the supplied dataset: 97 trades, 30 wins, 67 losses, 30.93% win rate, -7.00R net, PF 0.896, MaxDD 24R.
