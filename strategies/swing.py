"""Swing: RSI(2) en ETF de indice y Donchian solo largos en oro. Deciden una vez al dia, cerca del cierre."""
import json
import logging
from datetime import datetime

import pandas as pd

import data
import portfolio
import risk
import storage
from config import (DONCHIAN_ATR_LEN, DONCHIAN_ATR_STOP, DONCHIAN_ATR_TRAIL, DONCHIAN_ENTRY, DONCHIAN_EXIT,
                    DONCHIAN_MAX_DAYS, DONCHIAN_SYMBOL, DONCHIAN_TREND, RISK_SWING, RSI2_ATR_STOP, RSI2_ENTRY,
                    RSI2_EXIT, RSI2_MAX_DAYS, RSI2_SYMBOLS)
from indicators import atr, rsi, sma

log = logging.getLogger("bot")


def _days_held(df: pd.DataFrame, entry_time: str) -> int:
    d0 = pd.Timestamp(datetime.fromisoformat(entry_time).date())
    return int((df.index.tz_localize(None) > d0).sum())


def _stop_hit(pos: dict, df: pd.DataFrame) -> float | None:
    """Precio de salida si un minimo diario posterior a la entrada (o al ultimo ajuste del trailing) toco el stop.
    El dia de la entrada no cuenta: la entrada es a las 15:50 y el minimo de ese dia suele ser anterior."""
    meta = json.loads(pos.get("meta") or "{}")
    since = meta.get("trail_date") or datetime.fromisoformat(pos["entry_time"]).date().isoformat()
    bars = df[df.index.tz_localize(None) > pd.Timestamp(since)]
    for _, b in bars.iterrows():
        if b["Low"] <= pos["stop"]:
            return min(b["Open"], pos["stop"])
    return None


# ======================= RSI(2) =======================
def rsi2_run(now: datetime, equity: float, prices: dict, decide: bool):
    name = "rsi2"
    snap = {}
    for sym in RSI2_SYMBOLS:
        df = data.daily(sym)
        if df.empty or len(df) < 210:
            continue
        df["rsi2"] = rsi(df["Close"], 2)
        df["sma5"] = sma(df["Close"], 5)
        df["sma200"] = sma(df["Close"], 200)
        df["atr"] = atr(df, 14)
        b = df.iloc[-1]
        prices[sym] = float(b["Close"])
        is_today = df.index[-1].date() == now.date()
        snap[sym] = {"close": round(float(b["Close"]), 2), "rsi2": round(float(b["rsi2"]), 1),
                     "sma5": round(float(b["sma5"]), 2), "sma200": round(float(b["sma200"]), 2),
                     "setup": bool(b["Close"] > b["sma200"] and b["rsi2"] < RSI2_ENTRY)}

        for pos in storage.open_positions(name, sym):
            px = _stop_hit(pos, df)
            res = portfolio.close_position(pos, px, "Stop de emergencia 3xATR", now) if px else None
            if res is None and decide and is_today:
                held = _days_held(df, pos["entry_time"])
                why = ("Cierre > SMA5" if b["Close"] > b["sma5"] else f"RSI(2) > {RSI2_EXIT}" if b["rsi2"] > RSI2_EXIT
                       else f"{RSI2_MAX_DAYS} dias en la operacion" if held >= RSI2_MAX_DAYS else None)
                if why:
                    res = portfolio.close_position(pos, float(b["Close"]), why, now)
            if res:
                risk.register_result(name, res["pnl"], now)

    storage.set_state("snapshot_rsi2", {"updated": now.isoformat(timespec="seconds"), "symbols": snap})
    if not decide or storage.open_positions(name):
        return
    ev = risk.major_event_tomorrow(now.date())
    for sym in RSI2_SYMBOLS:  # solo una posicion a la vez (SPY y QQQ estan correlacionados)
        s = snap.get(sym)
        if not s or not s["setup"]:
            continue
        if ev:
            storage.log_activity("BLOQUEO", name, sym, f"Setup RSI(2) ignorado: manana hay {ev}", now)
            return
        df = data.daily(sym)
        a = float(atr(df, 14).iloc[-1])
        stop_dist = RSI2_ATR_STOP * a
        qty = equity * RISK_SWING * risk.size_multiplier() / stop_dist
        qty = portfolio.round_qty(min(qty, portfolio.cash(name) * 0.98 / s["close"]), True)
        ok, why = risk.can_enter(name, qty * stop_dist, equity, now, sym)
        if qty <= 0 or not ok:
            storage.log_activity("BLOQUEO", name, sym, f"Setup RSI(2) ignorado: {why or 'sin capital'}", now)
            return
        portfolio.open_position(name, sym, 1, qty, s["close"], s["close"] - stop_dist, None, stop_dist,
                                f"RSI(2) {s['rsi2']} < {RSI2_ENTRY} con cierre {s['close']} > SMA200 {s['sma200']}",
                                now)
        return


# ======================= Donchian oro =======================
def donchian_run(now: datetime, equity: float, prices: dict, decide: bool):
    name, sym = "donchian", DONCHIAN_SYMBOL
    df = data.daily(sym)
    if df.empty or len(df) < DONCHIAN_TREND + 5:
        return
    df["hh"] = df["High"].rolling(DONCHIAN_ENTRY).max().shift(1)
    df["ll"] = df["Low"].rolling(DONCHIAN_EXIT).min().shift(1)
    df["sma"] = sma(df["Close"], DONCHIAN_TREND)
    df["atr"] = atr(df, DONCHIAN_ATR_LEN)
    b = df.iloc[-1]
    close = float(b["Close"])
    prices[sym] = close
    is_today = df.index[-1].date() == now.date()
    storage.set_state("snapshot_donchian", {"updated": now.isoformat(timespec="seconds"), "symbols": {sym: {
        "close": round(close, 2), "max20": round(float(b["hh"]), 2), "min10": round(float(b["ll"]), 2),
        "sma100": round(float(b["sma"]), 2), "atr20": round(float(b["atr"]), 2),
        "setup": bool(close > b["hh"] and close > b["sma"])}}})

    for pos in storage.open_positions(name, sym):
        px = _stop_hit(pos, df)
        res = portfolio.close_position(pos, px, "Stop / trailing 3xATR", now) if px else None
        if res is None and decide and is_today:
            ext = max(pos["extreme"] or pos["entry_price"], close)
            trail = max(pos["stop"], ext - DONCHIAN_ATR_TRAIL * float(b["atr"]))
            meta = json.loads(pos.get("meta") or "{}")
            meta["trail_date"] = now.date().isoformat()
            storage.update_position(pos["id"], extreme=ext, stop=trail, meta=json.dumps(meta))
            held = _days_held(df, pos["entry_time"])
            r_now = (close - pos["entry_price"]) / pos["risk_per_share"]
            why = (f"Cierre < minimo de {DONCHIAN_EXIT} dias" if close < b["ll"]
                   else f"{DONCHIAN_MAX_DAYS} dias sin llegar a +1R" if held >= DONCHIAN_MAX_DAYS and r_now < 1 else None)
            if why:
                res = portfolio.close_position(pos, close, why, now)
        if res:
            risk.register_result(name, res["pnl"], now)

    if not decide or not is_today or storage.open_positions(name):
        return
    if close > b["hh"] and close > b["sma"]:
        ev = risk.major_event_tomorrow(now.date())
        if ev:
            storage.log_activity("BLOQUEO", name, sym, f"Ruptura ignorada: manana hay {ev}", now)
            return
        stop_dist = DONCHIAN_ATR_STOP * float(b["atr"])
        qty = equity * RISK_SWING * risk.size_multiplier() / stop_dist
        qty = portfolio.round_qty(min(qty, portfolio.cash(name) * 0.98 / close), True)
        ok, why = risk.can_enter(name, qty * stop_dist, equity, now, sym)
        if qty <= 0 or not ok:
            storage.log_activity("BLOQUEO", name, sym, f"Ruptura ignorada: {why or 'sin capital'}", now)
            return
        portfolio.open_position(name, sym, 1, qty, close, close - stop_dist, None, stop_dist,
                                f"Cierre {close:.2f} > maximo de 20 dias {b['hh']:.2f} y > SMA100 {b['sma']:.2f}", now)
