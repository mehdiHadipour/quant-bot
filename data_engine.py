import requests
import pandas as pd
import time

from logger import log

# GitHub Actions runners are hosted in US datacenters, and api.binance.com
# sometimes returns HTTP 451 (geo-blocked) from those IPs. data-api.binance.vision
# is Binance's official unauthenticated market-data mirror and is not subject to
# that block, so it's tried first; the others are kept as fallbacks.
BASE_URLS = [
    "https://data-api.binance.vision/api/v3/klines",
    "https://api.binance.com/api/v3/klines",
    "https://api1.binance.com/api/v3/klines",
    "https://api2.binance.com/api/v3/klines",
    "https://api3.binance.com/api/v3/klines",
]

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; AIQuantBot/1.0)"}


def fetch_klines(symbol, interval="1h", limit=300):
    # Fetches now run concurrently across symbols (see main.fetch_all_klines),
    # so every log line is tagged with "symbol interval" — otherwise
    # interleaved output from parallel threads would be unreadable,
    # especially on a small mobile screen viewing the Actions log.
    tag = f"{symbol} {interval}"
    params = {"symbol": symbol, "interval": interval, "limit": limit}

    for base_url in BASE_URLS:
        for attempt in range(3):
            try:
                resp = requests.get(base_url, params=params, headers=HEADERS, timeout=15)
                if resp.status_code == 200:
                    data = resp.json()
                    if data:
                        # Binance's kline array has more than OHLCV:
                        # [0]=open time [1]=open [2]=high [3]=low [4]=close
                        # [5]=volume [6]=close time [7]=quote volume
                        # [8]=trade count [9]=taker buy base volume [10]=taker
                        # buy quote volume [11]=ignore.
                        # "Taker buy volume" is how much of the candle's
                        # volume came from aggressive market-buy orders
                        # (hitting the ask) vs. passive/sell-side volume —
                        # a real, free proxy for order-flow/buy-sell
                        # pressure without needing tick-level trade data.
                        return pd.DataFrame([{
                            "open": float(x[1]),
                            "high": float(x[2]),
                            "low": float(x[3]),
                            "close": float(x[4]),
                            "volume": float(x[5]),
                            "taker_buy_volume": float(x[9]),
                        } for x in data])
                elif resp.status_code in (403, 418, 429):
                    # Rate limited / banned on this host — back off then try next host.
                    log.warning(f"[{tag}] {base_url} returned {resp.status_code}, backing off...")
                    time.sleep(2)
                elif resp.status_code == 451:
                    # Geo-blocked on this host, no point retrying it — jump to next host.
                    log.warning(f"[{tag}] {base_url} returned 451 (geo-blocked), trying next endpoint...")
                    break
                else:
                    log.warning(f"[{tag}] {base_url} returned status {resp.status_code}")
                    time.sleep(1)
            except requests.RequestException as e:
                log.warning(f"[{tag}] Request error on {base_url} (attempt {attempt + 1}/3): {e}")
                time.sleep(1)

    # Every Binance mirror failed — this is a whole-exchange outage/block,
    # not a single-mirror hiccup (the 5 URLs above are all still Binance).
    # OKX is a fully independent exchange with a free, unauthenticated
    # public klines endpoint and the same symbol convention for major
    # USDT pairs, so it's tried as a genuine last-resort fallback before
    # giving up on the symbol entirely for this cycle. Fails open exactly
    # like everything else in this module: any problem here just falls
    # through to the existing "return None" below, same as before this
    # fallback existed.
    okx_df = fetch_okx_klines(symbol, interval, limit)
    if okx_df is not None:
        log.info(f"[{tag}] Binance fully unavailable this cycle; used OKX fallback instead.")
        return okx_df

    log.error(f"[{tag}] Failed to fetch data from all endpoints")
    return None


OKX_KLINES_URL = "https://www.okx.com/api/v5/market/history-candles"
# OKX pairs are written "BTC-USDT" with a dash and always end in "-USDT"
# for the spot pairs this bot trades; Binance's "BTCUSDT" has no
# separator. Only symbols that map cleanly are attempted — anything
# unexpected (e.g. a future non-USDT quote asset) is skipped rather than
# guessed at.
OKX_INTERVAL_MAP = {"15m": "15m", "1h": "1H", "4h": "4H", "1d": "1D"}


AGG_TRADES_URLS = [
    "https://data-api.binance.vision/api/v3/aggTrades",
    "https://api.binance.com/api/v3/aggTrades",
    "https://api1.binance.com/api/v3/aggTrades",
]


def fetch_recent_agg_trades(symbol, minutes=55):
    """Real, individual trade-level data (Binance's public aggTrades
    endpoint — a plain REST call, no WebSocket/persistent connection
    needed, so this fits the existing 10-minute cron cycle without any
    architecture change). This is genuinely more granular than
    fetch_klines()'s taker_buy_volume, which is already an accurate
    aggregate BUT only at whole-candle resolution — aggTrades exposes
    where WITHIN that range the buying/selling actually happened,
    letting footprint.py compute a real point-of-control and
    imbalance-location, not just a total.

    `minutes` is capped under Binance's hard 1-hour startTime/endTime
    window limit for this endpoint (55 leaves a safety margin).

    CRYPTO-ONLY: this is a Binance-specific endpoint; WEEX-routed
    commodity/forex/index symbols have no equivalent here, so callers
    must only use this for CRYPTO_SYMBOLS. Returns None on any failure
    (rate limit, network, unsupported symbol) — fails open exactly like
    every other data source in this module, since this is an
    EXPERIMENTAL, informational-only signal (see main.py) that must
    never be able to block a trade by being unavailable.

    Returns a DataFrame with columns: price, qty, is_buyer_maker (True
    means the trade hit the bid — i.e. was SELLER-initiated; Binance's
    field name is confusingly the opposite of what it sounds like).
    """
    minutes = min(minutes, 55)
    end_ms = int(time.time() * 1000)
    start_ms = end_ms - minutes * 60 * 1000
    params = {"symbol": symbol, "startTime": start_ms, "endTime": end_ms, "limit": 1000}

    for base_url in AGG_TRADES_URLS:
        try:
            resp = requests.get(base_url, params=params, headers=HEADERS, timeout=15)
            if resp.status_code != 200:
                continue
            data = resp.json()
            if not data:
                return None
            rows = [{"price": float(t["p"]), "qty": float(t["q"]), "is_buyer_maker": bool(t["m"])} for t in data]
            return pd.DataFrame(rows)
        except (requests.RequestException, ValueError, KeyError) as e:
            log.warning(f"[aggTrades {symbol}] {base_url} failed: {e}")
            continue
    return None


def _to_okx_symbol(symbol):
    if not symbol.endswith("USDT"):
        return None
    base = symbol[: -len("USDT")]
    if not base:
        return None
    return f"{base}-USDT"


def fetch_okx_klines(symbol, interval="1h", limit=300):
    """Last-resort fallback for crypto klines when every Binance mirror
    has failed this cycle. OKX's public market-data endpoint needs no
    API key. Returns the same DataFrame shape as fetch_klines(), with
    taker_buy_volume left at 0.0 (OKX's public candle endpoint doesn't
    expose a taker-buy split the way Binance's does) — order_flow_score
    in indicators.py already treats a current_volume of 0 or an exactly
    50/50 buy_ratio as neutral, so this degrades the order-flow signal
    to "no opinion" for this cycle rather than fabricating a number."""
    okx_symbol = _to_okx_symbol(symbol)
    okx_interval = OKX_INTERVAL_MAP.get(interval)
    if okx_symbol is None or okx_interval is None:
        return None
    # OKX limits history-candles to 100 per request; cap accordingly
    # rather than silently returning fewer candles than asked for a
    # reason that's hard to trace back to this fallback specifically.
    okx_limit = min(limit, 100)
    params = {"instId": okx_symbol, "bar": okx_interval, "limit": okx_limit}
    try:
        resp = requests.get(OKX_KLINES_URL, params=params, headers=HEADERS, timeout=15)
        if resp.status_code != 200:
            log.warning(f"[OKX {symbol} {interval}] HTTP {resp.status_code}")
            return None
        payload = resp.json()
        rows = payload.get("data") if isinstance(payload, dict) else None
        if not rows:
            return None
        # OKX returns candles NEWEST-first; every other source/consumer
        # in this codebase expects OLDEST-first (chronological), so
        # reverse before building the frame.
        rows = list(reversed(rows))
        return pd.DataFrame([{
            "open": float(x[1]), "high": float(x[2]), "low": float(x[3]),
            "close": float(x[4]), "volume": float(x[5]),
            "taker_buy_volume": 0.0,
        } for x in rows])
    except (requests.RequestException, ValueError, TypeError, IndexError) as e:
        log.warning(f"[OKX {symbol} {interval}] fetch error: {e}")
        return None


WEEX_KLINES_URL = "https://api-contract.weex.com/capi/v3/market/klines"
WEEX_COMMODITY_SYMBOLS = {
    "XAUUSDT", "XAGUSDT", "CLUSDT", "NATGASUSDT",
    # Candidate additions (indices/stocks) researched from WEEX's public
    # TradFi pages, which describe gold/silver/oil/gas plus tokenized
    # stocks and "global indices" — but the EXACT ticker strings below
    # could not be verified against WEEX's live API from this environment
    # (no network access here). WEEX's own how-to examples use bare
    # tickers without a "USDT" suffix for some of these (e.g. "NAS100",
    # "TSLA", "HK50"), which may not match the "XAUUSDT"-style suffix
    # convention this codebase already uses for the four verified
    # symbols above. Before enabling any of these (via SYMBOLS in .env),
    # confirm the exact working ticker string from WEEX's contract list
    # or by testing fetch_weex_klines() against each candidate directly.
    "NAS100USDT", "US30USDT", "SPX500USDT", "HK50USDT",
    # V27.21 forex candidates — WEEX's own help docs confirm TradFi
    # includes "a wide range of major currency pairs" with USDT margin,
    # but exact ticker strings still couldn't be verified from this
    # environment (no network access here). Guessed following this
    # codebase's existing "XAUUSDT"-style suffix convention; forex pairs
    # conventionally quote as BASE+QUOTE (e.g. EURUSD), so the most likely
    # WEEX ticker shape is probably "EURUSDT" or plain "EURUSD" — test
    # both against fetch_weex_klines() before trusting either.
    "EURUSDT", "GBPUSDT", "USDJPYUSDT", "AUDUSDT",
}

def fetch_weex_klines(symbol, interval="1h", limit=300):
    """Fetch WEEX USDT-margined contract candles for commodity/TradFi symbols.

    Uses only public market data; no API key is required. WEEX documents the
    historical-kline endpoint and supports 15m/1h/4h/1d intervals.
    """
    params = {"symbol": symbol, "interval": interval, "limit": limit, "priceType": "LAST"}
    try:
        resp = requests.get(WEEX_KLINES_URL, params=params, headers=HEADERS, timeout=15)
        if resp.status_code != 200:
            log.warning(f"[WEEX {symbol} {interval}] HTTP {resp.status_code}")
            return None
        data = resp.json()
        if not isinstance(data, list) or not data:
            return None
        rows = []
        for x in data:
            if len(x) < 6:
                continue
            rows.append({
                "open": float(x[1]), "high": float(x[2]), "low": float(x[3]),
                "close": float(x[4]), "volume": float(x[5]),
                "taker_buy_volume": 0.0,
            })
        return pd.DataFrame(rows) if rows else None
    except (requests.RequestException, ValueError, TypeError, IndexError) as e:
        log.warning(f"[WEEX {symbol} {interval}] fetch error: {e}")
        return None

def fetch_market_klines(symbol, interval="1h", limit=300):
    if symbol in WEEX_COMMODITY_SYMBOLS:
        return fetch_weex_klines(symbol, interval, limit)
    return fetch_klines(symbol, interval, limit)


# Funding rate is a free, public number from perpetual futures markets
# (no API key needed) that reflects how crowded/expensive it currently is
# to be long vs. short. It's a genuine, widely-used positioning/sentiment
# signal — not a fabricated data source — and costs nothing extra to fetch.
#
# PRIMARY SOURCE — Binance USDT-M futures: unlike spot market data (which
# has the data-api.binance.vision unblocked mirror used above), Binance's
# derivatives/futures API (fapi.binance.com) does not have a documented,
# free, unblocked mirror. Regulatory geo-restrictions on leveraged
# derivatives trading tend to be stricter than on spot, and in practice
# this endpoint returns HTTP 451 from GitHub Actions' US-based runner
# IPs consistently, not just occasionally.
#
# FALLBACK SOURCE — Bybit's public v5 market-data endpoint (added
# v25.4): a different exchange's number, not Binance's — very close in
# practice (perp funding rates across major USDT-margined venues track
# each other closely via cross-exchange arbitrage) but not identical, so
# treat it as "market consensus funding", not "Binance's exact number".
# This is a public, unauthenticated, read-only market-data call — the
# same kind of request anyone's browser makes loading Bybit's website,
# no account or trading involved — used purely because Binance's futures
# endpoint is geo-blocked from GitHub's IP range; it does not bypass or
# spoof anything about Bybit's own access rules.
#
# The feature fails open either way (funding_score stays 0, never blocks
# a signal) — and logging a full WARNING for every one of the N symbols
# on every single 5-minute cycle would be noise for what, live, has
# consistently turned out to be a SYSTEMIC failure (both sources down
# together, every cycle) rather than a per-symbol issue — so per-symbol
# failures still only log at DEBUG (off by default), but this now also
# returns a short diagnostic string on failure so main.py can show the
# exact HTTP status/error from just the first symbol once per cycle,
# instead of the generic "both sources unavailable" guess used before.
FUNDING_URL = "https://fapi.binance.com/fapi/v1/premiumIndex"
FUNDING_URL_FALLBACK = "https://api.bybit.com/v5/market/tickers"


def fetch_funding_rate(symbol):
    """Return (rate, source, fail_reason) for `symbol`.
    rate is a float (e.g. 0.0001 = 0.01% per 8h) or None if it can't be
    fetched from either source — callers must treat None as "no
    opinion", never as 0.0, since a real 0.0 and a failed fetch mean
    very different things. source is "binance", "bybit", or None.
    fail_reason is None on success, otherwise a short string with the
    actual HTTP status/error from both attempts, for diagnosing WHY —
    e.g. distinguishing "both blocked with 451" (geo-block) from "both
    timed out" (transient network issue) from something else entirely.
    """
    binance_note = None
    try:
        resp = requests.get(
            FUNDING_URL, params={"symbol": symbol}, headers=HEADERS, timeout=10
        )
        if resp.status_code == 200:
            data = resp.json()
            rate = data.get("lastFundingRate")
            if rate is not None:
                return float(rate), "binance", None
            binance_note = "Binance 200 OK but no lastFundingRate in response"
        else:
            binance_note = f"Binance HTTP {resp.status_code}"
            log.debug(f"[{symbol}] {binance_note}, trying Bybit fallback...")
    except (requests.RequestException, ValueError, TypeError) as e:
        binance_note = f"Binance error: {e}"
        log.debug(f"[{symbol}] {binance_note}, trying Bybit fallback...")

    bybit_note = None
    try:
        resp = requests.get(
            FUNDING_URL_FALLBACK,
            params={"category": "linear", "symbol": symbol},
            headers=HEADERS,
            timeout=10,
        )
        if resp.status_code == 200:
            data = resp.json()
            ticker_list = (data.get("result") or {}).get("list") or []
            if ticker_list:
                rate = ticker_list[0].get("fundingRate")
                if rate not in (None, ""):
                    return float(rate), "bybit", None
            bybit_note = "Bybit 200 OK but no matching symbol/fundingRate in response"
        else:
            bybit_note = f"Bybit HTTP {resp.status_code}"
            log.debug(f"[{symbol}] {bybit_note}")
    except (requests.RequestException, ValueError, TypeError, IndexError) as e:
        bybit_note = f"Bybit error: {e}"
        log.debug(f"[{symbol}] {bybit_note}")

    return None, None, f"{binance_note} | {bybit_note}"
