"""Rotacion mensual de ETF por momentum dual: top 3 por media de retornos 3/6/12 meses, filtro SMA de 10 meses."""
import logging
from datetime import datetime

import pandas as pd

import data
import market
import portfolio
import storage
from config import (ROTATION_CASH, ROTATION_ENTER_ON_START, ROTATION_FRACTIONAL, ROTATION_MIN_DRIFT,
                    ROTATION_SMA_MONTHS, ROTATION_TOP_N, ROTATION_UNIVERSE)

log = logging.getLogger("bot")
NAME = "rotation"


def _monthly(now: datetime, include_current: bool) -> dict:
    out = {}
    for sym in ROTATION_UNIVERSE + [ROTATION_CASH]:
        df = data.daily(sym, period="3y")
        if df.empty:
            continue
        m = df["Close"].copy()
        m.index = m.index.tz_localize(None)
        m = m.resample("ME").last()
        if not include_current and m.index[-1].month == now.month and m.index[-1].year == now.year:
            m = m.iloc[:-1]
        out[sym] = {"monthly": m, "last": float(df["Close"].iloc[-1])}
    return out


def compute_targets(now: datetime, include_current: bool) -> tuple[dict, list]:
    data_m = _monthly(now, include_current)
    rows = []
    for sym in ROTATION_UNIVERSE:
        if sym not in data_m:
            continue
        c = data_m[sym]["monthly"]
        if len(c) < 13:
            continue
        score = ((c.iloc[-1] / c.iloc[-4] + c.iloc[-1] / c.iloc[-7] + c.iloc[-1] / c.iloc[-13]) / 3 - 1) * 100
        sma10 = c.iloc[-ROTATION_SMA_MONTHS:].mean()
        rows.append({"symbol": sym, "score": round(float(score), 2),
                     "vs_sma10": round(float((c.iloc[-1] / sma10 - 1) * 100), 2),
                     "above": bool(c.iloc[-1] > sma10), "month": c.index[-1].strftime("%Y-%m")})
    rows.sort(key=lambda r: r["score"], reverse=True)
    weights = {}
    for i, r in enumerate(rows):
        r["rank"] = i + 1
        if i < ROTATION_TOP_N:
            tgt = r["symbol"] if r["above"] else ROTATION_CASH
            weights[tgt] = weights.get(tgt, 0) + 1.0 / ROTATION_TOP_N
    prices = {s: v["last"] for s, v in data_m.items()}
    return {"weights": weights, "prices": prices}, rows


def rebalance(now: datetime, prices: dict, include_current: bool, reason: str):
    tg, rows = compute_targets(now, include_current)
    prices.update(tg["prices"])
    storage.set_state("rotation_ranking", {"updated": now.isoformat(timespec="seconds"), "basis": reason,
                                           "rows": rows, "weights": tg["weights"]})
    if not tg["weights"]:
        storage.log_activity("AVISO", NAME, "", "Sin datos suficientes para la rotacion", now)
        return
    _, eq = portfolio.sleeve_equity(NAME, prices)
    held = {p["symbol"]: p for p in storage.open_positions(NAME)}

    # 1) ventas: lo que sale del top o se reduce
    for sym, pos in held.items():
        tgt_val = tg["weights"].get(sym, 0) * eq
        cur_val = pos["qty"] * prices.get(sym, pos["entry_price"])
        if tgt_val == 0:
            portfolio.close_position(pos, prices[sym], f"Sale de la rotacion ({reason})", now)
        elif cur_val - tgt_val > ROTATION_MIN_DRIFT * eq:
            # reduccion parcial: se cierra y se reabre con la cantidad nueva para llevar el registro limpio
            portfolio.close_position(pos, prices[sym], f"Rebalanceo, reduce peso ({reason})", now)
            held[sym] = None

    # 2) compras: lo que entra o se aumenta
    for sym, w in sorted(tg["weights"].items(), key=lambda kv: -kv[1]):
        px = prices.get(sym)
        if not px:
            continue
        pos = held.get(sym)
        cur_val = pos["qty"] * px if pos else 0.0
        tgt_val = w * eq
        if pos and abs(tgt_val - cur_val) <= ROTATION_MIN_DRIFT * eq:
            continue
        if pos:
            portfolio.close_position(pos, px, f"Rebalanceo, ajusta peso ({reason})", now)
        budget = min(tgt_val, portfolio.cash(NAME)) * 0.998
        qty = portfolio.round_qty(budget / px, ROTATION_FRACTIONAL)
        if qty > 0:
            row = next((r for r in rows if r["symbol"] == sym), None)
            why = (f"Top {row['rank']}: puntaje {row['score']}%, {row['vs_sma10']:+.1f}% vs SMA10m" if row
                   else "Efectivo: un ETF del top 3 esta bajo su SMA de 10 meses")
            portfolio.open_position(NAME, sym, 1, qty, px, None, None, None, f"{why} ({reason})", now)
    storage.set_state("rotation_last_rebalance", now.date().isoformat())


def run(now: datetime, prices: dict, decide: bool):
    for p in storage.open_positions(NAME):
        if p["symbol"] not in prices:
            px = data.last_price(p["symbol"])
            if px:
                prices[p["symbol"]] = px
    if not storage.open_positions(NAME) and ROTATION_ENTER_ON_START and not storage.get_state("rotation_last_rebalance"):
        rebalance(now, prices, include_current=False, reason="arranque con la senal del ultimo cierre de mes")
        return
    if decide and market.is_last_trading_day_of_month(now.date()) \
            and storage.get_state("rotation_last_rebalance") != now.date().isoformat():
        rebalance(now, prices, include_current=True, reason=f"rebalanceo mensual {now:%Y-%m}")
    elif decide and storage.get_state("rotation_preview_date") != now.date().isoformat():
        # vista previa diaria (no opera): como quedaria el ranking si el mes cerrara hoy
        _, rows = compute_targets(now, include_current=True)
        storage.set_state("rotation_preview", {"updated": now.isoformat(timespec="seconds"), "rows": rows})
        storage.set_state("rotation_preview_date", now.date().isoformat())
