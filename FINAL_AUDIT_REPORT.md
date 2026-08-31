# Quant Bot V30.8.1 Final Audit

## Mandatory Fibonacci policy
- REQUIRE_FIB_OTE=1 by default.
- No live signal is accepted unless the directional 61.8%-78.6% Fibonacci OTE is true on the latest closed bar.
- Backtest applies the same hard OTE gate to BUY and SELL.
- Fibonacci uses prior completed bars only (shift(1)); no look-ahead.
- Telegram signal includes OTE status, swing high/low, 61.8% and 78.6% levels.

## Signal components
ICT liquidity sweep, displacement, MSS/FVG/OB, Fibonacci OTE, Ichimoku 9/26/52, MACD 12/26/9, order-flow/taker-volume proxy, CVD/absorption proxy, volume profile POC/VAH/VAL/HVN/LVN, hyper-liquidity proxy, session weighting, fundamental/news veto, whale sidecar veto, risk engine, trailing/partial lock, encrypted state, Telegram alerts.

## Data limitations
Footprint/order-flow is a proxy from OHLCV + taker_buy_volume. True tick/LOB footprint requires historical trade/Level-2 data and is not fabricated. Fundamental/news/whale context is neutral when no timestamped external data is supplied, except configured news provider may veto on available live data.

## Validation
- Python compile: PASS
- pytest: 17 PASS
- unittest discovery: 15 PASS
- backtest runner: PASS
- all backtest trades satisfy fib_ote: PASS
- ZIP integrity: checked after creation
