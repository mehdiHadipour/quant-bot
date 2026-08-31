# V30 Parameter Research

The research was deliberately compact to reduce curve-fitting. Ichimoku presets considered were 9/26/52 and 10/30/60; the classic 9/26/52 was retained because it is the strongest broadly supported baseline and because the tested crypto source found 9/26/52 best among its tested presets. ATR 14 was retained as the base volatility measure. The execution filter search compared displacement and score thresholds on the supplied 14-symbol dataset.

Selected V30 config: **Ichimoku 9/26/52, ATR 14, displacement >= 0.85 ATR, final score >= 70**.

Selection criterion: risk-aware comparison using Net R, Profit Factor and Max Drawdown; not win rate alone. This is not a guarantee of future performance.

Important: the supplied historical dataset contains OHLCV + taker-buy volume, not timestamped historical news or full order-book/tick data. Fundamental/news therefore remains neutral in this historical run; Footprint and Hyper-Liquidity remain proxies. Live mode can use the external news/order-flow sources configured by the bot.

V30.2 Fibonacci search: lookbacks 20/30/40/50/60 and retracement zones including 0.618-0.786 and 0.50-0.786. Best in-sample compact grid result was 50 or 60 bars with 0.50-0.786: 97 trades, -7R, PF 0.896. This remains negative; the setting is retained as a modest confirmation layer, not evidence of standalone Fibonacci edge.
