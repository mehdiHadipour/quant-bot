"""Refresh whale_bias.json from real Hyperliquid top-trader positions.

Run on its own schedule (see .github/workflows/whale_bias.yml) -- separate
from the 5-minute trading cycle, because the Hyperliquid leaderboard payload
is tens of megabytes and whale positioning doesn't need 5-minute freshness.

Writes a plain {"<COIN>": {"bias": ..., "confidence": ...}, ...} JSON file.
smart_context.py already reads this shape via WHALE_BIAS_FILE -- nothing
else needs to change for the trading bot to start using it.

Fails soft: if Hyperliquid is unreachable this cycle, the previous
whale_bias.json is left untouched (never overwritten with an empty/stale
guess), so a transient network hiccup can't wipe out the last known-good
read.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hyperliquid_whales import whale_bias_by_coin  # noqa: E402

OUTPUT_PATH = Path(__file__).resolve().parents[1] / "whale_bias.json"


def main():
    result = whale_bias_by_coin(n_traders=25, window="month", min_account_value=50_000.0)
    if not result:
        print("No whale data fetched this run (Hyperliquid unreachable or empty) "
              "-- leaving existing whale_bias.json untouched.")
        return 0

    OUTPUT_PATH.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    print(f"Wrote {len(result)} coin(s) to {OUTPUT_PATH}:")
    for coin, info in sorted(result.items()):
        print(f"  {coin}: {info['bias']} (confidence={info['confidence']}, "
              f"longs={info['n_long']}, shorts={info['n_short']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
