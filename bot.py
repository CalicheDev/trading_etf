"""Bot de simulacion (paper trading). Consulta el mercado cada 15 minutos en horario de NYSE y ejecuta:
- Intradia ORB/VWAP (15m)      - Swing RSI(2) en SPY/QQQ
- Swing Donchian en oro (GLD)  - Rotacion mensual de ETF

Uso:
    python bot.py            # bucle continuo
    python bot.py --once     # un solo ciclo (prueba)
    python bot.py --reset    # borra la simulacion y empieza de cero con el capital inicial
"""
import argparse
import logging
import sys
import time
import traceback
from datetime import datetime, timedelta
from logging.handlers import RotatingFileHandler

import market
import portfolio
import risk
import storage
from config import DAILY_DECISION_TIME, DB_PATH, LOG_FILE, LOOP_MINUTES, SLEEVES
from strategies import intraday, rotation, swing

log = logging.getLogger("bot")


def setup_logging():
    log.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    fh = RotatingFileHandler(LOG_FILE, maxBytes=2_000_000, backupCount=3, encoding="utf-8")
    fh.setFormatter(fmt)
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    log.addHandler(fh)
    log.addHandler(sh)


def snapshot_equity(now: datetime, prices: dict):
    ts = now.isoformat(timespec="seconds")
    total = 0.0
    for s in SLEEVES:
        pv, eq = portfolio.sleeve_equity(s, prices)
        storage.insert_equity(ts, s, portfolio.cash(s), pv, eq)
        total += eq
    storage.insert_equity(ts, "total", None, None, total)
    storage.set_state("last_prices", prices)
    return total


def cycle(now: datetime):
    sess = market.session(now.date())
    if not sess:
        log.info("Hoy no hay sesion en NYSE")
        return
    s_open, s_close = sess
    prices = storage.get_state("last_prices", {}) or {}
    equity = portfolio.total_equity(prices)
    risk.update_period_marks(now, equity)

    h, m = DAILY_DECISION_TIME.split(":")
    decision_at = min(now.replace(hour=int(h), minute=int(m), second=0, microsecond=0),
                      s_close - timedelta(minutes=10))
    decide = now >= decision_at and storage.get_state("daily_decision_date") != now.date().isoformat()

    steps = [
        ("intraday", lambda: intraday.run(now, s_open, s_close, equity, prices)),
        ("rsi2", lambda: swing.rsi2_run(now, equity, prices, decide)),
        ("donchian", lambda: swing.donchian_run(now, equity, prices, decide)),
        ("rotation", lambda: rotation.run(now, prices, decide)),
    ]
    for name, fn in steps:
        try:
            fn()
        except Exception as e:  # una estrategia con error no detiene a las demas
            log.error("Error en %s: %s\n%s", name, e, traceback.format_exc())
            storage.log_activity("ERROR", name, "", str(e), now)
    if decide:
        storage.set_state("daily_decision_date", now.date().isoformat())
    total = snapshot_equity(now, prices)
    storage.set_state("last_cycle", now.isoformat(timespec="seconds"))
    log.info("Ciclo completo. Capital total %.2f USD", total)


def next_wake(now: datetime) -> datetime:
    sess = market.session(now.date())
    if sess and now < sess[1] + timedelta(minutes=2):
        s_open, s_close = sess
        if now < s_open:
            return s_open + timedelta(minutes=1)
        # siguiente cierre de vela de 15 min + 75 s para que el proveedor publique la vela
        nxt = now.replace(second=0, microsecond=0) + timedelta(minutes=LOOP_MINUTES - now.minute % LOOP_MINUTES)
        nxt += timedelta(seconds=75)
        h, m = DAILY_DECISION_TIME.split(":")
        special = [min(now.replace(hour=int(h), minute=int(m), second=30, microsecond=0),
                       s_close - timedelta(minutes=10)),
                   s_close - timedelta(minutes=5) + timedelta(seconds=30)]
        for sp in special:
            if now < sp < nxt:
                nxt = sp
        return min(nxt, s_close + timedelta(minutes=1))
    return market.next_session_open(now + timedelta(minutes=5)) + timedelta(minutes=1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--reset", action="store_true")
    args = ap.parse_args()
    setup_logging()
    if args.reset and DB_PATH.exists():
        DB_PATH.unlink()
        print("Simulacion reiniciada.")
    storage.init()
    if storage.get_state("started") is None:
        storage.set_state("started", datetime.now(market.NY).isoformat(timespec="seconds"))
        storage.log_activity("INFO", "global", "", "Simulacion iniciada con 5,000 USD", datetime.now(market.NY))
    if args.once:
        cycle(datetime.now(market.NY))
        return
    log.info("Bot iniciado. Ctrl+C para detener.")
    while True:
        now = datetime.now(market.NY)
        sess = market.session(now.date())
        if sess and sess[0] <= now <= sess[1] + timedelta(minutes=1):
            try:
                cycle(now)
            except Exception as e:
                log.error("Error en el ciclo: %s\n%s", e, traceback.format_exc())
        wake = next_wake(datetime.now(market.NY))
        log.info("Proximo ciclo: %s", wake.strftime("%Y-%m-%d %H:%M:%S %Z"))
        while datetime.now(market.NY) < wake:
            time.sleep(min(60, max(1, (wake - datetime.now(market.NY)).total_seconds())))


if __name__ == "__main__":
    main()
