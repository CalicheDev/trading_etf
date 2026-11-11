"""Dashboard del bot. Ejecutar con:  streamlit run dashboard.py"""
import json
import sqlite3
from datetime import datetime

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from config import DB_PATH, INITIAL_CAPITAL, SLEEVES

st.set_page_config(page_title="Bot de trading (simulacion)", layout="wide")

LABELS = {"intraday": "Intradia ORB/VWAP", "rotation": "Rotacion ETF", "rsi2": "Swing RSI(2)",
          "donchian": "Swing oro Donchian", "total": "Total", "global": "Global"}
EXIT_RULES = {
    "intraday": "Stop / objetivo 1.5R / cierre 5 min antes del final de la sesion",
    "rsi2": "Cierre > SMA5, RSI(2) > 70, 7 dias o stop 3xATR",
    "donchian": "Trailing 3xATR, cierre < minimo de 10 dias, o 10 dias sin +1R",
    "rotation": "Ultimo dia habil del mes si sale del top 3 o cae bajo su SMA de 10 meses",
}


def q(sql, args=()):
    if not DB_PATH.exists():
        return pd.DataFrame()
    with sqlite3.connect(DB_PATH) as c:
        return pd.read_sql_query(sql, c, params=args)


def state(key, default=None):
    df = q("SELECT value FROM state WHERE key=?", (key,))
    return json.loads(df["value"].iloc[0]) if not df.empty else default


def stats(trades: pd.DataFrame) -> dict:
    if trades.empty:
        return {"Operaciones": 0, "Win rate": "-", "Profit factor": "-", "Expectativa (R)": "-", "P&L (USD)": 0.0}
    wins, losses = trades[trades.pnl > 0], trades[trades.pnl <= 0]
    pf = wins.pnl.sum() / -losses.pnl.sum() if losses.pnl.sum() < 0 else float("inf")
    r = trades.r_multiple.dropna()
    return {"Operaciones": len(trades), "Win rate": f"{len(wins) / len(trades):.0%}",
            "Profit factor": "inf" if pf == float("inf") else f"{pf:.2f}",
            "Expectativa (R)": f"{r.mean():+.2f}" if len(r) else "-", "P&L (USD)": round(trades.pnl.sum(), 2)}


@st.fragment(run_every="60s")
def render():
    if not DB_PATH.exists():
        st.warning("Todavia no hay datos. Inicia el bot con `run_bot.bat` (o `python bot.py`).")
        return
    prices = state("last_prices", {}) or {}
    eq = q("SELECT * FROM equity")
    tot = eq[eq.sleeve == "total"]
    equity_now = float(tot.equity.iloc[-1]) if not tot.empty else INITIAL_CAPITAL
    pnl = equity_now - INITIAL_CAPITAL
    dd = state("drawdown", 0.0) or 0.0
    day0 = state("day_start_equity", equity_now) or equity_now
    last_cycle = state("last_cycle", "-")

    st.title("Bot de trading — simulacion")
    st.caption(f"Ultimo ciclo: {last_cycle} (hora de Nueva York) · datos de Yahoo Finance, pueden tener ~15 min de retraso · "
               "se actualiza cada 60 s")

    c = st.columns(5)
    c[0].metric("Capital", f"${equity_now:,.2f}", f"{pnl:+,.2f} ({pnl / INITIAL_CAPITAL:+.2%})")
    c[1].metric("P&L de hoy", f"{equity_now - day0:+,.2f}")
    c[2].metric("Drawdown", f"{dd:.2%}")
    open_pos = q("SELECT * FROM positions")
    risk_usd = sum(max(0.0, (r.entry_price - r.stop) * r.side) * r.qty for r in open_pos.itertuples() if r.stop)
    c[3].metric("Riesgo abierto", f"${risk_usd:,.2f}", f"{risk_usd / equity_now:.2%} del capital (max. 4%)",
                delta_color="off")
    c[4].metric("Posiciones abiertas", len(open_pos))

    # estado de riesgo
    flags = []
    if state("kill_until"):
        flags.append(f"KILL SWITCH activo hasta {state('kill_until')[:10]}")
    if state("half_size"):
        flags.append("Tamano al 50% por drawdown >= 8%")
    for s in SLEEVES:
        cd = state(f"cooldown_{s}")
        if cd and datetime.fromisoformat(cd) > datetime.now(datetime.fromisoformat(cd).tzinfo):
            flags.append(f"Cooldown en {LABELS[s]} hasta {cd[:10]}")
    if flags:
        st.error(" · ".join(flags))
    else:
        st.success("Sin restricciones de riesgo activas")

    # curva de capital
    if not eq.empty:
        eq["ts"] = pd.to_datetime(eq.ts)
        fig = go.Figure()
        for s in ["total", *SLEEVES]:
            d = eq[eq.sleeve == s]
            fig.add_scatter(x=d.ts, y=d.equity, name=LABELS[s], mode="lines",
                            line=dict(width=3 if s == "total" else 1.5))
        fig.update_layout(height=360, margin=dict(l=10, r=10, t=30, b=10), yaxis_title="USD",
                          legend=dict(orientation="h", y=1.1), title="Curva de capital")
        st.plotly_chart(fig, width="stretch")

    trades = q("SELECT * FROM trades ORDER BY id DESC")
    tab1, tab2, tab3, tab4, tab5 = st.tabs(["Posiciones abiertas", "Resultados por estrategia",
                                            "Operaciones cerradas", "Senales y condiciones", "Registro"])
    with tab1:
        if open_pos.empty:
            st.info("No hay posiciones abiertas.")
        else:
            rows = []
            for r in open_pos.itertuples():
                px = prices.get(r.symbol, r.entry_price)
                rows.append({"Estrategia": LABELS[r.strategy], "Simbolo": r.symbol,
                             "Lado": "Largo" if r.side == 1 else "Corto", "Cantidad": r.qty,
                             "Entrada": round(r.entry_price, 2), "Precio": round(px, 2),
                             "Stop": round(r.stop, 2) if r.stop else None,
                             "Objetivo": round(r.target, 2) if r.target else None,
                             "P&L no realizado": round((px - r.entry_price) * r.qty * r.side, 2),
                             "Abierta": r.entry_time[:16].replace("T", " "),
                             "Cuando sale": EXIT_RULES[r.strategy], "Motivo de entrada": r.reason})
            st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
    with tab2:
        rows = []
        for s in SLEEVES:
            last = eq[eq.sleeve == s].equity
            rows.append({"Estrategia": LABELS[s], "Capital asignado": SLEEVES[s],
                         "Capital actual": round(float(last.iloc[-1]), 2) if len(last) else SLEEVES[s],
                         **stats(trades[trades.strategy == s])})
        rows.append({"Estrategia": "Total", "Capital asignado": INITIAL_CAPITAL,
                     "Capital actual": round(equity_now, 2), **stats(trades)})
        st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
        st.caption("Referencia del backtest: intradia 15m WR 47–54%, PF 1.1–1.4 · RSI(2) WR 68–75%, PF 1.6–2.3 · "
                   "oro Donchian WR 53%, PF 1.6 · rotacion CAGR 8.9%, DD max 16%. "
                   "Revisa una estrategia si su PF real cae por debajo de 0.7x el del backtest tras 30+ operaciones.")
    with tab3:
        if trades.empty:
            st.info("Todavia no hay operaciones cerradas.")
        else:
            t = trades.copy()
            t["strategy"] = t.strategy.map(LABELS)
            t["side"] = t.side.map({1: "Largo", -1: "Corto"})
            t = t[["exit_time", "strategy", "symbol", "side", "qty", "entry_price", "exit_price", "pnl",
                   "r_multiple", "entry_reason", "exit_reason"]]
            t.columns = ["Cierre", "Estrategia", "Simbolo", "Lado", "Cantidad", "Entrada", "Salida", "P&L",
                         "R", "Motivo de entrada", "Motivo de salida"]
            st.dataframe(t, width="stretch", hide_index=True)
    with tab4:
        st.subheader("Intradia (ultima vela de 15 min cerrada)")
        snap = state("snapshot_intraday")
        if snap:
            st.caption(f"Actualizado {snap['updated']}. Entrada larga: ORB (cierre > maximo del rango de apertura, "
                       "> EMA55, RSI > 55) o VWAP (cruce al alza, EMA55 subiendo, RSI > 50), siempre con volumen > 1.2x.")
            st.dataframe(pd.DataFrame(snap["symbols"]).T, width="stretch")
        st.subheader("Swing RSI(2)")
        snap = state("snapshot_rsi2")
        if snap:
            st.caption("Entrada: cierre > SMA200 y RSI(2) < 10, al cierre del dia.")
            st.dataframe(pd.DataFrame(snap["symbols"]).T, width="stretch")
        st.subheader("Swing oro Donchian")
        snap = state("snapshot_donchian")
        if snap:
            st.caption("Entrada: cierre > maximo de 20 dias y > SMA100, al cierre del dia.")
            st.dataframe(pd.DataFrame(snap["symbols"]).T, width="stretch")
        st.subheader("Rotacion de ETF")
        rk = state("rotation_ranking")
        if rk:
            st.caption(f"Cartera objetivo vigente ({rk['basis']}): "
                       + ", ".join(f"{k} {v:.0%}" for k, v in rk["weights"].items()))
            st.dataframe(pd.DataFrame(rk["rows"]), width="stretch", hide_index=True)
        pv = state("rotation_preview")
        if pv:
            st.caption(f"Vista previa si el mes cerrara hoy ({pv['updated'][:10]}); no opera hasta el ultimo dia habil:")
            st.dataframe(pd.DataFrame(pv["rows"]), width="stretch", hide_index=True)
    with tab5:
        act = q("SELECT * FROM activity ORDER BY rowid DESC LIMIT 300")
        if not act.empty:
            act["strategy"] = act.strategy.map(lambda s: LABELS.get(s, s))
            act.columns = ["Hora", "Tipo", "Estrategia", "Simbolo", "Detalle"]
            st.dataframe(act, width="stretch", hide_index=True)


render()
