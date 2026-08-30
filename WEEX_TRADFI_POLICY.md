# WEEX TradFi approval policy

A TradFi symbol is eligible for live trading only after: API eligibility, historical data availability, mandatory Fibonacci OTE, liquidity/order-flow/Volume Profile/session gates, and out-of-sample performance approval.

Overall symbol approval defaults to:
- >=30 closed trades
- Profit Factor >=1.25
- Net R > 0
- Max drawdown <=8R
- Win rate >=45%

Direction policy after >=8 trades:
- NORMAL: PF >=1.05 and Net R >=0
- STRICT: PF <1.05 or Net R <0
- BLOCK: PF <0.90 and Net R <0

This allows a profitable direction to remain available even when the opposite direction is weak.
