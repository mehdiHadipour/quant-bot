"""Post-trade sentinel: detect weak symbols, directions, sessions and gates."""
from __future__ import annotations

from collections import defaultdict

ALERT_MIN_TRADES = 8
BLOCK_PF = 0.90
STRICT_PF = 1.05
STRICT_NET_R = 0.0


def _pf(values):
    pos = sum(x for x in values if x > 0)
    neg = -sum(x for x in values if x < 0)
    return pos / neg if neg > 0 else (99.0 if pos > 0 else 0.0)


def diagnose(history_rows):
    groups = defaultdict(list)
    for row in history_rows:
        try:
            r = float(row.get("r_multiple", 0))
        except (TypeError, ValueError):
            continue
        symbol = str(row.get("symbol", "")).upper()
        direction = str(row.get("direction", "")).upper()
        session = str(row.get("session", "UNKNOWN")).upper()
        groups[(symbol, direction)].append(r)
        groups[(symbol, "ALL")].append(r)
        groups[("SESSION:" + session, "ALL")].append(r)
    alerts = []
    policies = {}
    for (key, direction), vals in groups.items():
        if len(vals) < ALERT_MIN_TRADES:
            continue
        net = sum(vals); pf = _pf(vals); wr = sum(v > 0 for v in vals) / len(vals)
        if key.startswith("SESSION:"):
            if pf < STRICT_PF and net < 0:
                alerts.append({"scope": "SESSION", "name": key[8:], "reason": "negative session expectancy", "trades": len(vals), "net_r": net, "pf": pf})
            continue
        if direction != "ALL":
            level = "BLOCK" if pf < BLOCK_PF and net < 0 else "STRICT" if pf < STRICT_PF or net < STRICT_NET_R else "NORMAL"
            policies.setdefault(key, {})[direction] = {"level": level, "trades": len(vals), "net_r": net, "pf": pf, "win_rate": wr}
            if level != "NORMAL":
                alerts.append({"scope": "DIRECTION", "symbol": key, "direction": direction, "reason": f"{level}: weak direction", "trades": len(vals), "net_r": net, "pf": pf})
        else:
            if pf < BLOCK_PF and net < 0:
                alerts.append({"scope": "SYMBOL", "symbol": key, "reason": "symbol is materially negative", "trades": len(vals), "net_r": net, "pf": pf})
    return {"alerts": alerts, "direction_policies": policies}
