"""Reglas de riesgo globales: limites diarios/semanales, drawdown, cooldown y eventos macro."""
import csv
import logging
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import storage
from config import (COOLDOWN_DAYS, COOLDOWN_LOSSES, DAILY_LOSS_LIMIT, DD_HALF_SIZE, DD_KILL, DD_LONG_ONLY,
                    EVENT_BLACKOUT_MIN, EVENTS_FILE, KILL_SWITCH_DAYS, MAX_OPEN_RISK, TZ, WEEKLY_LOSS_LIMIT)
import portfolio

log = logging.getLogger("bot")
NY = ZoneInfo(TZ)


# ---------- Eventos macro ----------
def load_events() -> list[dict]:
    out = []
    if not EVENTS_FILE.exists():
        return out
    with open(EVENTS_FILE, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            try:
                ts = datetime.strptime(row["datetime"].strip(), "%Y-%m-%d %H:%M").replace(tzinfo=NY)
                out.append({"ts": ts, "name": row["name"].strip(), "scope": row.get("scope", "all").strip()})
            except (KeyError, ValueError):
                continue
    return out


def in_blackout(now: datetime, symbol: str = "") -> str | None:
    for ev in load_events():
        if ev["scope"] == "oil" and symbol not in ("USO", "BNO", "XLE", "CL", "MCL"):
            continue
        if abs((now - ev["ts"]).total_seconds()) <= EVENT_BLACKOUT_MIN * 60:
            return ev["name"]
        # FOMC: sin entradas desde 15 min antes hasta 1 h despues (rueda de prensa)
        if ev["name"].upper().startswith("FOMC") and timedelta(0) <= now - ev["ts"] <= timedelta(hours=1):
            return ev["name"]
    return None


def major_event_tomorrow(today: date) -> str | None:
    """Swing: no se abre la vispera de FOMC, CPI o NFP."""
    for ev in load_events():
        if ev["scope"] == "all" and ev["ts"].date() == today + timedelta(days=1):
            return ev["name"]
        # viernes -> el siguiente dia habil es lunes
        if today.weekday() == 4 and ev["scope"] == "all" and ev["ts"].date() == today + timedelta(days=3):
            return ev["name"]
    return None


# ---------- Estado diario / semanal / drawdown ----------
def update_period_marks(now: datetime, equity: float):
    d = now.date().isoformat()
    if storage.get_state("day_mark_date") != d:
        storage.set_state("day_mark_date", d)
        storage.set_state("day_start_equity", equity)
    week = f"{now.isocalendar().year}-W{now.isocalendar().week}"
    if storage.get_state("week_mark") != week:
        storage.set_state("week_mark", week)
        storage.set_state("week_start_equity", equity)
    peak = max(storage.get_state("peak_equity", equity), equity)
    storage.set_state("peak_equity", peak)
    dd = 1 - equity / peak if peak > 0 else 0.0
    storage.set_state("drawdown", dd)
    # escalera de drawdown con histeresis
    half = storage.get_state("half_size", False)
    if dd >= DD_HALF_SIZE and not half:
        storage.set_state("half_size", True)
        storage.log_activity("RIESGO", "global", "", f"Drawdown {dd:.1%}: tamano al 50%", now)
    elif half and dd < 0.04:
        storage.set_state("half_size", False)
        storage.log_activity("RIESGO", "global", "", "Drawdown < 4%: tamano completo restablecido", now)
    if dd >= DD_KILL and not storage.get_state("kill_until"):
        until = (now + timedelta(days=KILL_SWITCH_DAYS)).isoformat()
        storage.set_state("kill_until", until)
        storage.log_activity("RIESGO", "global", "", f"KILL SWITCH: drawdown {dd:.1%}. Sin operar hasta {until[:10]}", now)
    return dd


def size_multiplier() -> float:
    return 0.5 if storage.get_state("half_size", False) else 1.0


def kill_active(now: datetime) -> bool:
    until = storage.get_state("kill_until")
    if not until:
        return False
    if now >= datetime.fromisoformat(until):
        storage.set_state("kill_until", None)
        storage.set_state("peak_equity", None)  # nuevo maximo de referencia tras la auditoria
        return False
    return True


def cooldown_active(strategy: str, now: datetime) -> bool:
    until = storage.get_state(f"cooldown_{strategy}")
    return bool(until) and now < datetime.fromisoformat(until)


def register_result(strategy: str, pnl: float, now: datetime):
    key = f"consec_losses_{strategy}"
    n = storage.get_state(key, 0)
    n = n + 1 if pnl < 0 else 0
    if n >= COOLDOWN_LOSSES:
        until = now
        added = 0
        while added < COOLDOWN_DAYS:
            until += timedelta(days=1)
            if until.weekday() < 5:
                added += 1
        until = until.replace(hour=0, minute=0, second=0)
        storage.set_state(f"cooldown_{strategy}", until.isoformat())
        storage.log_activity("RIESGO", strategy, "", f"{n} perdidas seguidas: cooldown hasta {until.date()}", now)
        n = 0
    storage.set_state(key, n)


def can_enter(strategy: str, new_risk_usd: float, equity: float, now: datetime, symbol: str = "") -> tuple[bool, str]:
    if kill_active(now):
        return False, "kill switch activo"
    dd = storage.get_state("drawdown", 0.0)
    if dd >= DD_LONG_ONLY and strategy != "rotation":
        return False, f"drawdown {dd:.1%}: solo rotacion"
    day0 = storage.get_state("day_start_equity", equity)
    if equity - day0 <= -DAILY_LOSS_LIMIT * day0:
        return False, "limite de perdida diaria alcanzado"
    week0 = storage.get_state("week_start_equity", equity)
    if equity - week0 <= -WEEKLY_LOSS_LIMIT * week0:
        return False, "limite de perdida semanal alcanzado"
    if cooldown_active(strategy, now):
        return False, "cooldown por perdidas consecutivas"
    if portfolio.open_risk() + new_risk_usd > MAX_OPEN_RISK * equity:
        return False, "riesgo abierto total > 4%"
    ev = in_blackout(now, symbol)
    if ev and strategy != "rotation":
        return False, f"bloqueo por evento: {ev}"
    return True, ""
