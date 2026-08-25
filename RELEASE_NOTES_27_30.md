# V27.30 — Smart Money / Context Fusion

Adds a single entry-quality layer combining:
- pullback/anti-chase entry location;
- live footprint when recent aggregate trades are available, otherwise a historical-safe taker-flow/rejection proxy;
- UTC global-session context;
- optional per-symbol whale bias bridge (`WHALE_BIAS_JSON` / `WHALE_BIAS_FILE`);
- optional fundamental headline scoring;
- hard filters remain opt-in for footprint/news, while missing external data fails neutral.

The screenshot supplied by the user was reviewed. It advertises World Monitor for market-regime detection, Claude for entry strategy design, and ForexBot for automation. It does not expose a proprietary formula or executable rule set, so no unsupported proprietary rule was copied. V27.30 incorporates the useful public concept — explicit market-regime/context filtering — without pretending to have Claude/World Monitor internals.

Important: Hyperdash documentation describes trader discovery, asset-focused trader views, and copy/contra-trading, but no public machine-readable API contract was verified for this package. Therefore V27.30 does not fabricate an API. Whale data can be injected as a timestamped JSON snapshot; missing snapshots are neutral.
