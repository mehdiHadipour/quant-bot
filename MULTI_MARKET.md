# V27.13 Multi-Market

Default scanner: 14 crypto markets + XAUUSDT (gold), XAGUSDT (silver), CLUSDT (crude oil), NATGASUSDT (natural gas) on WEEX contract market data.

Commodity symbols use the public WEEX Kline API. Crypto continues using the existing Binance/Bybit market-data stack. Funding is skipped for commodities.

Live execution remains governed by the existing risk engine and GitHub Secrets. The bot does not place a trade merely because a market is listed: all existing signal gates still apply.

WEEX availability can change; the bot fails closed for unavailable symbols and never substitutes an unknown ticker.
