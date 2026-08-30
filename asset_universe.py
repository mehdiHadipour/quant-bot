"""WEEX multi-asset discovery and safety gating.

TradFi contracts are discovered from WEEX V3 rather than hard-coded into the
live trading list. A symbol is NEVER promoted to live trading merely because
an exchange endpoint returns a price: it must be API-tradable and pass the
bot's own out-of-sample approval policy.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import requests

from logger import log

WEEX_BASE = "https://api-contract.weex.com"
CACHE = Path("state/weex_universe.json")
BOOTSTRAP = Path("config/weex_tradfi_candidates.json")
TIMEOUT = 12


def _csv_env(name: str) -> set[str]:
    raw = os.getenv(name, "")
    return {x.strip().upper() for x in raw.split(",") if x.strip()}


def fetch_weex_universe() -> list[dict[str, Any]]:
    """Return current WEEX TradFi contracts that are API-tradable.

    Failure is fail-closed for live TradFi: an unavailable discovery endpoint
    never turns a guessed symbol into a tradeable symbol.
    """
    try:
        symbols = requests.get(
            f"{WEEX_BASE}/capi/v3/market/apiTradingSymbols", timeout=TIMEOUT
        )
        symbols.raise_for_status()
        allowed = {str(x).upper() for x in symbols.json() if x}
        info = requests.get(
            f"{WEEX_BASE}/capi/v3/market/exchangeInfo",
            params={"contractType": "TRADIFI_PERPETUAL"},
            timeout=TIMEOUT,
        )
        info.raise_for_status()
        rows = (info.json() or {}).get("symbols", [])
        out = []
        for row in rows:
            sym = str(row.get("symbol", "")).upper()
            if sym and sym in allowed and row.get("contractType") == "TRADIFI_PERPETUAL":
                out.append(row)
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        CACHE.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
        return out
    except (requests.RequestException, ValueError, TypeError, OSError) as exc:
        log.warning("WEEX TradFi discovery failed: %s", exc)
        return []


def load_cached_universe() -> list[dict[str, Any]]:
    try:
        return json.loads(CACHE.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return []


def bootstrap_candidates() -> list[str]:
    try:
        data = json.loads(BOOTSTRAP.read_text(encoding="utf-8"))
        return sorted({str(x).upper() for x in data if x})
    except (OSError, ValueError, TypeError):
        return []


def classify_symbol(symbol: str, row: dict[str, Any] | None = None) -> str:
    row = row or {}
    subs = " ".join(str(x).upper() for x in row.get("underlyingSubType", []))
    text = f"{symbol.upper()} {str(row.get('underlyingType', '')).upper()} {subs}"
    if any(k in text for k in ("GOLD", "SILVER", "COPPER", "METAL")) or symbol.upper().startswith(("XAU", "XAG")):
        return "METAL"
    if any(k in text for k in ("OIL", "CRUDE", "BRENT", "NATURAL_GAS", "GAS", "ENERGY")) or symbol.upper() in {"CLUSDT", "BZUSDT", "NATGASUSDT"}:
        return "ENERGY"
    if any(k in text for k in ("FOREX", "FX", "CURRENCY")):
        return "FOREX"
    if any(k in text for k in ("INDEX", "INDICES")) or symbol.upper() in {"GER40USDT", "KOSPIUSDT", "KODEX200USDT"} or symbol.upper().startswith(("GER", "KOSPI", "MTSI")):
        return "INDEX"
    if any(k in text for k in ("ETF", "FUND")) or symbol.upper().startswith(("SPY", "QQQ", "SOXL", "SQQQ")):
        return "ETF"
    return "STOCK"


def tradfi_candidates() -> list[dict[str, Any]]:
    rows = fetch_weex_universe()
    if not rows:
        rows = load_cached_universe()
    by = {str(r.get("symbol", "")).upper(): r for r in rows if r.get("symbol")}
    result = []
    for sym in sorted(set(by) | set(bootstrap_candidates())):
        result.append({"symbol": sym, "asset_class": classify_symbol(sym, by.get(sym)), "api_verified": sym in by})
    return result


def approved_symbols() -> set[str]:
    """Only explicitly approved symbols are allowed into live TradFi flow."""
    explicit = _csv_env("TRADFI_APPROVED_SYMBOLS")
    if not explicit:
        return set()
    try:
        report = json.loads(Path(os.getenv("TRADFI_APPROVAL_FILE", "state/tradfi_approval.json")).read_text(encoding="utf-8"))
        approved = {str(x).upper() for x in report.get("approved_symbols", [])}
        return explicit & approved
    except (OSError, ValueError, TypeError):
        return set()


def live_tradfi_symbols() -> set[str]:
    if os.getenv("TRADFI_ENABLED", "1").strip().lower() in {"0", "false", "no", "off"}:
        return set()
    if os.getenv("TRADFI_LIVE_APPROVAL_REQUIRED", "1").strip().lower() in {"0", "false", "no", "off"}:
        return {x["symbol"] for x in tradfi_candidates() if x.get("api_verified")}
    return approved_symbols()


def is_tradfi_symbol(symbol: str) -> bool:
    sym = symbol.upper()
    if sym in {x.upper() for x in bootstrap_candidates()}:
        return True
    cached = load_cached_universe()
    return any(str(r.get("symbol", "")).upper() == sym and r.get("contractType", "TRADIFI_PERPETUAL") == "TRADIFI_PERPETUAL" for r in cached)
