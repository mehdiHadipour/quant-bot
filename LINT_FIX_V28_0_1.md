# v28.0.1 — CI/Lint Fix

- Removed an unnecessary `f` prefix from a static backtest report heading (Ruff F541).
- Ensured `fvg` is initialized before the indicator result payload is built, preventing F821/F841 regressions when the FVG block is edited.
- The current `main.py` does not assign unused `live_15m`/`live_1d` variables; it uses the completed-candle data structure directly.
- This release is intended to be copied as a complete repository replacement, not merged file-by-file into an older version.
