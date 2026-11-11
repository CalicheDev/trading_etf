"""Broker simulado: cada estrategia tiene su propia porcion de capital (sleeve)."""
import json
import logging
import math
from datetime import datetime

import storage
from config import COMMISSION_PER_SHARE, SLEEVES, SLIPPAGE_PCT

log = logging.getLogger("bot")


def cash(sleeve: str) -> float:
    return storage.get_state(f"cash_{sleeve}", SLEEVES[sleeve])


def _set_cash(sleeve: str, value: float):
    storage.set_state(f"cash_{sleeve}", round(value, 6))


def _commission(qty: float) -> float:
    return round(abs(qty) * COMMISSION_PER_SHARE, 4)


def round_qty(qty: float, fractional: bool) -> float:
    if qty <= 0:
        return 0.0
    return math.floor(qty * 1000) / 1000 if fractional else float(math.floor(qty))


def open_position(strategy, symbol, side, qty, price, stop, target, risk_ps, reason, now: datetime,
                  meta=None, slippage=True) -> dict | None:
    if qty <= 0:
        return None
    fill = price * (1 + SLIPPAGE_PCT * side) if slippage else price
    comm = _commission(qty)
    c = cash(strategy)
    if side == 1:
        c -= qty * fill + comm
    else:
        c += qty * fill - comm
    _set_cash(strategy, c)
    pos = dict(strategy=strategy, symbol=symbol, side=side, qty=qty, entry_price=fill,
               entry_time=now.isoformat(timespec="seconds"), stop=stop, target=target,
               risk_per_share=risk_ps, extreme=fill, reason=reason,
               meta=json.dumps({**(meta or {}), "entry_commission": comm}))
    pos["id"] = storage.insert_position(pos)
    side_txt = "LARGO" if side == 1 else "CORTO"
    stop_txt = f"{stop:.2f}" if stop else "-"
    tgt_txt = f"{target:.2f}" if target else "-"
    storage.log_activity("ENTRADA", strategy, symbol,
                         f"{side_txt} {qty:g} @ {fill:.2f} | stop {stop_txt} | objetivo {tgt_txt} | {reason}", now)
    log.info("[%s] ENTRADA %s %s %g @ %.2f (%s)", strategy, side_txt, symbol, qty, fill, reason)
    return pos


def close_position(pos: dict, price: float, reason: str, now: datetime, slippage=True) -> dict:
    side = pos["side"]
    fill = price * (1 - SLIPPAGE_PCT * side) if slippage else price
    comm = _commission(pos["qty"])
    c = cash(pos["strategy"])
    if side == 1:
        c += pos["qty"] * fill - comm
    else:
        c -= pos["qty"] * fill + comm
    _set_cash(pos["strategy"], c)
    meta = json.loads(pos.get("meta") or "{}")
    total_comm = comm + meta.get("entry_commission", 0)
    pnl = (fill - pos["entry_price"]) * pos["qty"] * side - total_comm
    risk = (pos["risk_per_share"] or 0) * pos["qty"]
    r_mult = pnl / risk if risk > 0 else None
    storage.insert_trade(dict(strategy=pos["strategy"], symbol=pos["symbol"], side=side, qty=pos["qty"],
                              entry_price=pos["entry_price"], entry_time=pos["entry_time"], exit_price=fill,
                              exit_time=now.isoformat(timespec="seconds"), pnl=round(pnl, 2),
                              r_multiple=round(r_mult, 3) if r_mult is not None else None,
                              commission=round(total_comm, 4), entry_reason=pos.get("reason"),
                              exit_reason=reason))
    storage.delete_position(pos["id"])
    r_txt = f" ({r_mult:+.2f}R)" if r_mult is not None else ""
    storage.log_activity("SALIDA", pos["strategy"], pos["symbol"],
                         f"{pos['qty']:g} @ {fill:.2f} | P&L {pnl:+.2f} USD{r_txt} | {reason}", now)
    log.info("[%s] SALIDA %s @ %.2f P&L %.2f (%s)", pos["strategy"], pos["symbol"], fill, pnl, reason)
    return {"pnl": pnl, "r": r_mult}


def sleeve_equity(sleeve: str, prices: dict) -> tuple[float, float]:
    """Devuelve (valor de posiciones, equity) usando los ultimos precios conocidos."""
    pv = 0.0
    for p in storage.open_positions(strategy=sleeve):
        px = prices.get(p["symbol"], p["entry_price"])
        pv += p["qty"] * px * p["side"]
    c = cash(sleeve)
    return pv, c + pv


def total_equity(prices: dict) -> float:
    return sum(sleeve_equity(s, prices)[1] for s in SLEEVES)


def open_risk() -> float:
    """Riesgo abierto en USD: distancia al stop actual por cantidad (0 si no tiene stop)."""
    total = 0.0
    for p in storage.open_positions():
        if p["stop"]:
            total += max(0.0, (p["entry_price"] - p["stop"]) * p["side"]) * p["qty"]
    return total
