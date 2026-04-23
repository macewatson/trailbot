from copy import deepcopy


def _effective_trail(trade: dict, current_price: float, vwap: float | None) -> float:
    """Trail distance, optionally adjusted by VWAP band position."""
    trail = trade["trail_amount"]
    if not trade.get("vwap_aware") or vwap is None or vwap <= 0:
        return trail
    vwap_upper = vwap * 1.01
    vwap_lower = vwap * 0.99
    if current_price > vwap_upper:
        return trail * 0.75   # price above VWAP band — tighten
    if current_price < vwap_lower:
        return trail * 1.25   # price below VWAP band — widen
    return trail


def process_stop(trade: dict, current_price: float, vwap: float = None) -> dict:
    """
    Pure function — no side effects.
    Returns updated trade dict. Sets exit_triggered=True if stop is hit.
    current_stop never decreases for LONG positions (max() enforced everywhere).
    """
    t = deepcopy(trade)
    mode = t["stop_mode"]

    if mode == "HARD":
        if current_price <= t["hard_stop"]:
            t["exit_triggered"] = True
            return t

        if t.get("trail_trigger") and current_price >= t["trail_trigger"]:
            t["stop_mode"] = "TRAILING"
            t["status"] = "TRAILING"
            mode = "TRAILING"
            # fall through to TRAILING logic this same tick

        else:
            return t

    if mode == "TRAILING":
        t["high_water_mark"] = max(t["high_water_mark"], current_price)
        effective = _effective_trail(t, current_price, vwap)
        new_stop = t["high_water_mark"] - effective
        t["current_stop"] = max(t["current_stop"], new_stop)

        if current_price <= t["current_stop"]:
            t["exit_triggered"] = True
            return t

        if t.get("tighten_at") and current_price >= t["tighten_at"]:
            t["stop_mode"] = "TIGHT"
            t["status"] = "TIGHTENED"
            mode = "TIGHT"
            # fall through to TIGHT logic this same tick

        else:
            return t

    if mode == "TIGHT":
        t["high_water_mark"] = max(t["high_water_mark"], current_price)
        new_stop = t["high_water_mark"] - t["tight_trail_amount"]
        t["current_stop"] = max(t["current_stop"], new_stop)

        if current_price <= t["current_stop"]:
            t["exit_triggered"] = True

    return t
