# V30.9.7 Configuration Guide

`manual_settings.json` is the single source of truth for research and live strategy parameters.

## Per-tool controls
Each entry under `tools` supports:
- `enabled`: true/false
- `mode`: `score` or `hard`
- `weight`: contribution weight

## Regime
`regime` supports BULL, BEAR, RANGE and TRANSITION. It is computed from the same data path used by live/backtest. `hard_gate=false` is the safe research default: regime is recorded and available for strategy routing without silently destroying the sample.

## Sessions
Each session can be enabled/disabled and has `start`, `end`, `weight`, `score_bonus`, and `min_score`. London/New York use DST-aware IANA time zones in `smart_context.py`.

## Symbol profiles
Every symbol has an override object. Future validated out-of-sample research can promote per-symbol/per-regime parameters without changing strategy code.

## Safety
Risk limits remain independent of signal settings. Never disable risk controls for live trading.
