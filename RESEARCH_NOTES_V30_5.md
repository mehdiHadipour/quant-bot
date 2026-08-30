# V30.5 research notes

MACD is used as a confirmation layer, not a standalone trigger. The standard 12/26/9 configuration is used because it is a widely documented baseline; Fidelity's technical-analysis material documents MACD 12/26/9 and interprets signal-line and zero-line crossings as bullish/bearish momentum cues.

Session logic is timezone/DST aware. Tokyo is 09:00-18:00 local and London is 08:00-17:00 local; their overlap is therefore represented explicitly. IG notes that the Tokyo-London overlap is historically less liquid than London-New York, so V30.5 gives it a lower quality score and requires the Asia-only location/OTE gate.

The historical dataset contains OHLCV/taker-buy data but no complete historical order-book/tick feed or timestamped fundamental news stream. Therefore Footprint/Hyper-Liquidity are proxies and fundamental/news remains neutral unless a timestamped sidecar is supplied. No synthetic data is inserted.

Parameter screening on the supplied sample tested score thresholds 50-75. The best in-sample result among this small screen was score threshold 60, but it remained negative, so it is not presented as proof of profitability.
