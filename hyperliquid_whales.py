"""Real whale-position confirmation using Hyperliquid's public, no-auth API.

This does NOT scrape hyperdash.com (it has no public/documented API, and
scraping its rendered UI would be fragile and against its terms). Instead
it goes straight to the same public, unauthenticated Hyperliquid endpoints
that HyperDash itself is built on -- Hyperliquid positions are on-chain and
public by design:

  GET  https://stats-data.hyperliquid.xyz/Mainnet/leaderboard
       -> every trader's account value + PnL/ROI/volume across
          day/week/month/allTime windows. Same JSON the official
          https://app.hyperliquid.xyz/leaderboard page reads.

  POST https://api.hyperliquid.xyz/info  {"type": "batchClearinghouseStates", "users": [...]}
       -> each address's current open perpetual positions (coin, signed
          size, notional value). No API key, no login required.

Output shape matches what smart_context.py already expects from a
WHALE_BIAS_FILE sidecar: {"<COIN>": {"bias": "BUY"|"SELL"|"NEUTRAL",
"confidence": 0..1}, ...}. Nothing in smart_context.py needs to change --
scripts/update_whale_bias.py just needs to write this dict out to the
file named by config.WHALE_BIAS_FILE.

Fails soft everywhere: any network/parse problem yields an empty dict,
which smart_context.py already treats as NEUTRAL. It never fabricates a
bias when data isn't available.
"""
from __future__ import annotations
import time
import requests

LEADERBOARD_URL = "https://stats-data.hyperliquid.xyz/Mainnet/leaderboard"
INFO_URL = "https://api.hyperliquid.xyz/info"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; AIQuantBot-WhaleTracker/1.0)"}

# The leaderboard payload is tens of megabytes and trader identities don't
# meaningfully change hour to hour, so the top-address list is cached
# in-process for this long between re-fetches.
_LEADERBOARD_TTL_SECONDS = 6 * 3600
_cache = {"ts": 0.0, "addresses": []}


def fetch_top_trader_addresses(n=25, window="month", min_account_value=50_000.0):
    """Return up to `n` wallet addresses of the most profitable Hyperliquid
    traders, ranked by realized PnL within `window`
    (one of "day", "week", "month", "allTime").

    Cached in-process for _LEADERBOARD_TTL_SECONDS. On any failure, returns
    whatever was last cached (possibly an empty list) rather than raising.
    """
    now = time.time()
    if _cache["addresses"] and now - _cache["ts"] < _LEADERBOARD_TTL_SECONDS:
        return _cache["addresses"]

    try:
        resp = requests.get(LEADERBOARD_URL, headers=HEADERS, timeout=45)
        resp.raise_for_status()
        rows = resp.json().get("leaderboardRows", [])
    except (requests.RequestException, ValueError, AttributeError):
        return _cache["addresses"]

    ranked = []
    for row in rows:
        addr = row.get("ethAddress")
        if not addr:
            continue
        try:
            account_value = float(row.get("accountValue") or 0)
        except (TypeError, ValueError):
            account_value = 0.0
        if account_value < min_account_value:
            continue
        perf = dict(row.get("windowPerformances") or [])
        window_stats = perf.get(window) or {}
        try:
            pnl = float(window_stats.get("pnl") or 0)
        except (TypeError, ValueError):
            pnl = 0.0
        if pnl <= 0:
            continue  # only genuinely profitable traders for this window
        ranked.append((pnl, addr))

    ranked.sort(key=lambda t: t[0], reverse=True)
    top_addresses = [addr for _, addr in ranked[:n]]
    if top_addresses:
        _cache["addresses"] = top_addresses
        _cache["ts"] = now
    return top_addresses


def fetch_positions(addresses, batch_size=50):
    """Return {address: [{"coin": str, "szi": float, "notional": float}, ...]}
    for every address's currently open perpetual positions.
    A missing/failed batch is simply omitted (fail-soft), never raised.
    """
    out = {}
    for i in range(0, len(addresses), batch_size):
        chunk = addresses[i:i + batch_size]
        try:
            resp = requests.post(
                INFO_URL,
                json={"type": "batchClearinghouseStates", "users": chunk},
                headers=HEADERS,
                timeout=30,
            )
            resp.raise_for_status()
            states = resp.json()
        except (requests.RequestException, ValueError):
            continue
        if not isinstance(states, list):
            continue
        for addr, state in zip(chunk, states):
            positions = []
            for asset_position in (state or {}).get("assetPositions", []):
                pos = asset_position.get("position", {})
                coin = pos.get("coin")
                try:
                    szi = float(pos.get("szi") or 0)
                    notional = abs(float(pos.get("positionValue") or 0))
                except (TypeError, ValueError):
                    continue
                if coin and szi != 0 and notional > 0:
                    positions.append({"coin": coin, "szi": szi, "notional": notional})
            out[addr] = positions
    return out


def aggregate_positions(positions_by_address):
    """Pure aggregation step (no network) -- kept separate so it's directly
    unit-testable. Weights each trader's direction by position notional, so
    one whale's $5M long counts far more than another's $5K long.

    Returns {"<COIN>": {"bias": "BUY"|"SELL"|"NEUTRAL", "confidence": float,
    "n_long": int, "n_short": int}, ...}
    """
    per_coin = {}
    for positions in positions_by_address.values():
        for p in positions:
            slot = per_coin.setdefault(
                p["coin"], {"long_notional": 0.0, "short_notional": 0.0, "n_long": 0, "n_short": 0}
            )
            if p["szi"] > 0:
                slot["long_notional"] += p["notional"]
                slot["n_long"] += 1
            else:
                slot["short_notional"] += p["notional"]
                slot["n_short"] += 1

    result = {}
    for coin, slot in per_coin.items():
        total = slot["long_notional"] + slot["short_notional"]
        if total <= 0:
            continue
        long_share = slot["long_notional"] / total
        if long_share >= 0.60:
            bias, confidence = "BUY", long_share
        elif long_share <= 0.40:
            bias, confidence = "SELL", 1.0 - long_share
        else:
            bias, confidence = "NEUTRAL", 0.5
        result[coin] = {
            "bias": bias,
            "confidence": round(confidence, 3),
            "n_long": slot["n_long"],
            "n_short": slot["n_short"],
        }
    return result


def whale_bias_by_coin(n_traders=25, window="month", min_account_value=50_000.0):
    """End-to-end: top profitable traders -> their open positions -> per-coin
    bias. Returns {} on any upstream failure (treated as NEUTRAL by callers).
    """
    addresses = fetch_top_trader_addresses(n=n_traders, window=window, min_account_value=min_account_value)
    if not addresses:
        return {}
    positions_by_address = fetch_positions(addresses)
    if not positions_by_address:
        return {}
    return aggregate_positions(positions_by_address)
