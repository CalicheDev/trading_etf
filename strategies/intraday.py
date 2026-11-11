"""Intradia ORB / VWAP + EMA55, RSI y volumen en velas de 15 minutos (misma logica que el script de TradingView)."""
import logging
from datetime import datetime, time, timedelta

import pandas as pd

import data
import portfolio
import risk
import storage
from config import (ATR_LEN, ATR_STOP, EMA_LEN, ENTRY_END, ENTRY_START, INTRADAY_FRACTIONAL, INTRADAY_SYMBOLS,
                    MAX_TRADES_PER_DAY, RISK_INTRADAY, RR, RSI_LEN, VOL_MULT)
from indicators import atr, ema, rsi, session_vwap, sma

log = logging.getLogger("bot")
NAME = "intraday"
BAR = timedelta(minutes=15)


def _t(s: str) -> time:
    h, m = s.split(":")
    return time(int(h), int(m))


def _manage(pos: dict, bars: pd.DataFrame, now: datetime) -> dict | None:
    """Revisa stop/objetivo con las velas desde la entrada. Si ambos se tocan en la misma vela, cuenta el stop."""
    entry_t = datetime.fromisoformat(pos["entry_time"])
    floor = entry_t - timedelta(minutes=entry_t.minute % 15, seconds=entry_t.second)
    for ts, b in bars[bars.index >= floor].iterrows():
        side = pos["side"]
        hit_stop = b["Low"] <= pos["stop"] if side == 1 else b["High"] >= pos["stop"]
        if hit_stop:
            px = min(b["Open"], pos["stop"]) if side == 1 else max(b["Open"], pos["stop"])
            return portfolio.close_position(pos, px, "Stop loss", now)
        if ts >= floor + BAR:
            hit_tgt = b["High"] >= pos["target"] if side == 1 else b["Low"] <= pos["target"]
            if hit_tgt:
                return portfolio.close_position(pos, pos["target"], "Objetivo 1.5R", now, slippage=False)
    return None


def run(now: datetime, sess_open: datetime, sess_close: datetime, equity: float, prices: dict):
    flatten_at = sess_close - timedelta(minutes=5)
    entry_end = min(datetime.combine(now.date(), _t(ENTRY_END), now.tzinfo), sess_close - timedelta(minutes=30))
    entry_start = datetime.combine(now.date(), _t(ENTRY_START), now.tzinfo)
    snapshot = {}

    for sym in INTRADAY_SYMBOLS:
        closed, alldf = data.intraday_15m(sym, now)
        if alldf.empty:
            continue
        last = float(alldf["Close"].iloc[-1])
        prices[sym] = last

        # ---- gestion de posiciones abiertas ----
        for pos in storage.open_positions(NAME, sym):
            res = _manage(pos, alldf, now)
            if res is None and now >= flatten_at:
                res = portfolio.close_position(pos, last, "Cierre fin de sesion", now)
            if res:
                risk.register_result(NAME, res["pnl"], now)

        if closed.empty or closed.index[-1].date() != now.date():
            continue

        # ---- indicadores sobre velas cerradas ----
        df = closed.copy()
        df["ema"] = ema(df["Close"], EMA_LEN)
        df["rsi"] = rsi(df["Close"], RSI_LEN)
        df["atr"] = atr(df, ATR_LEN)
        df["vwap"] = session_vwap(df)
        df["volsma"] = sma(df["Volume"], 20)
        today = df[df.index.date == now.date()]
        b, p = df.iloc[-1], df.iloc[-2]
        or_h, or_l = float(today["High"].iloc[0]), float(today["Low"].iloc[0])
        or_done = len(today) >= 2
        ema_up = b["ema"] > df["ema"].iloc[-6]
        ema_dn = b["ema"] < df["ema"].iloc[-6]
        vol_ok = b["Volume"] > VOL_MULT * b["volsma"]
        date_key = now.date().isoformat()
        orb_used = storage.get_state(f"orb_used_{sym}_{date_key}", False)

        orb_l = (not orb_used) and or_done and b["Close"] > or_h and p["Close"] <= or_h and b["Close"] > b["ema"] and b["rsi"] > 55 and vol_ok
        orb_s = (not orb_used) and or_done and b["Close"] < or_l and p["Close"] >= or_l and b["Close"] < b["ema"] and b["rsi"] < 45 and vol_ok
        vw_l = b["Close"] > b["ema"] and ema_up and b["Close"] > b["vwap"] and p["Close"] <= p["vwap"] and b["rsi"] > 50 and vol_ok
        vw_s = b["Close"] < b["ema"] and ema_dn and b["Close"] < b["vwap"] and p["Close"] >= p["vwap"] and b["rsi"] < 50 and vol_ok

        snapshot[sym] = {
            "bar": closed.index[-1].strftime("%H:%M"), "close": round(float(b["Close"]), 2),
            "ema55": round(float(b["ema"]), 2), "vwap": round(float(b["vwap"]), 2), "rsi": round(float(b["rsi"]), 1),
            "vol_ratio": round(float(b["Volume"] / b["volsma"]), 2) if b["volsma"] else None,
            "or_high": round(or_h, 2), "or_low": round(or_l, 2), "atr": round(float(b["atr"]), 3),
            "trend": "alcista" if b["Close"] > b["ema"] and ema_up else "bajista" if b["Close"] < b["ema"] and ema_dn else "neutral",
            "signal": "ORB L" if orb_l else "ORB S" if orb_s else "VWAP L" if vw_l else "VWAP S" if vw_s else "-",
        }

        # evaluar cada vela una sola vez y solo si es reciente
        bar_key = f"intraday_lastbar_{sym}"
        if storage.get_state(bar_key) == str(closed.index[-1]):
            continue
        storage.set_state(bar_key, str(closed.index[-1]))
        signal_time = closed.index[-1] + BAR
        if not (entry_start <= signal_time <= entry_end) or now - signal_time > BAR:
            continue
        if not (orb_l or orb_s or vw_l or vw_s):
            continue
        if storage.open_positions(NAME, sym):
            continue
        trades_key = f"intraday_trades_{sym}_{date_key}"
        if storage.get_state(trades_key, 0) >= MAX_TRADES_PER_DAY:
            continue

        side = 1 if (orb_l or vw_l) else -1
        kind = ("ORB" if (orb_l or orb_s) else "VWAP") + (" L" if side == 1 else " S")
        stop_dist = ATR_STOP * float(b["atr"])
        qty = equity * RISK_INTRADAY * risk.size_multiplier() / stop_dist
        qty = min(qty, portfolio.cash(NAME) * 0.95 / last)
        qty = portfolio.round_qty(qty, INTRADAY_FRACTIONAL)
        if qty <= 0:
            storage.log_activity("BLOQUEO", NAME, sym, f"Senal {kind} sin capital suficiente en la porcion", now)
            continue
        ok, why = risk.can_enter(NAME, qty * stop_dist, equity, now, sym)
        if not ok:
            storage.log_activity("BLOQUEO", NAME, sym, f"Senal {kind} ignorada: {why}", now)
            continue
        reason = (f"{kind}: cierre {b['Close']:.2f} vs EMA55 {b['ema']:.2f}, VWAP {b['vwap']:.2f}, "
                  f"RSI {b['rsi']:.0f}, volumen x{b['Volume'] / b['volsma']:.1f}")
        portfolio.open_position(NAME, sym, side, qty, last, last - side * stop_dist,
                                last + side * stop_dist * RR, stop_dist, reason, now)
        storage.set_state(trades_key, storage.get_state(trades_key, 0) + 1)
        if kind.startswith("ORB"):
            storage.set_state(f"orb_used_{sym}_{date_key}", True)

    if snapshot:
        storage.set_state("snapshot_intraday", {"updated": now.isoformat(timespec="seconds"), "symbols": snapshot})
