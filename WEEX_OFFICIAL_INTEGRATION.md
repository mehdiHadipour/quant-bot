# WEEX integration reference

The implementation uses the official WEEX Contract V3 interfaces:

- `/capi/v3/market/apiTradingSymbols` — authoritative API-trading universe
- `/capi/v3/market/exchangeInfo?contractType=TRADIFI_PERPETUAL` — TradFi contract metadata
- `/capi/v3/market/klines` — live candles
- `/capi/v3/market/historyKlines` — historical candles for research
- `/capi/v3/market/premiumIndex` — funding information

The bot deliberately treats API-tradability as separate from the existence of a market-data price.
