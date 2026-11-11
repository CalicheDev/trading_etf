"""Persistencia en SQLite: posiciones, operaciones, curva de capital, registro y estado."""
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime

from config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS positions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    strategy TEXT, symbol TEXT, side INTEGER, qty REAL,
    entry_price REAL, entry_time TEXT, stop REAL, target REAL,
    risk_per_share REAL, extreme REAL, reason TEXT, meta TEXT
);
CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    strategy TEXT, symbol TEXT, side INTEGER, qty REAL,
    entry_price REAL, entry_time TEXT, exit_price REAL, exit_time TEXT,
    pnl REAL, r_multiple REAL, commission REAL, entry_reason TEXT, exit_reason TEXT
);
CREATE TABLE IF NOT EXISTS equity (
    ts TEXT, sleeve TEXT, cash REAL, positions_value REAL, equity REAL
);
CREATE TABLE IF NOT EXISTS activity (
    ts TEXT, level TEXT, strategy TEXT, symbol TEXT, message TEXT
);
CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, value TEXT);
CREATE INDEX IF NOT EXISTS ix_equity_ts ON equity(ts);
CREATE INDEX IF NOT EXISTS ix_activity_ts ON activity(ts);
"""


@contextmanager
def conn():
    c = sqlite3.connect(DB_PATH, timeout=30)
    c.row_factory = sqlite3.Row
    try:
        yield c
        c.commit()
    finally:
        c.close()


def init():
    with conn() as c:
        c.executescript(SCHEMA)


def get_state(key, default=None):
    with conn() as c:
        row = c.execute("SELECT value FROM state WHERE key=?", (key,)).fetchone()
    return json.loads(row["value"]) if row else default


def set_state(key, value):
    with conn() as c:
        c.execute("INSERT OR REPLACE INTO state(key, value) VALUES(?, ?)", (key, json.dumps(value, default=str)))


def log_activity(level, strategy, symbol, message, now: datetime | None = None):
    ts = (now or datetime.now()).isoformat(timespec="seconds")
    with conn() as c:
        c.execute("INSERT INTO activity VALUES(?,?,?,?,?)", (ts, level, strategy, symbol, message))


def open_positions(strategy=None, symbol=None):
    q, args = "SELECT * FROM positions WHERE 1=1", []
    if strategy:
        q += " AND strategy=?"; args.append(strategy)
    if symbol:
        q += " AND symbol=?"; args.append(symbol)
    with conn() as c:
        return [dict(r) for r in c.execute(q, args).fetchall()]


def insert_position(p: dict) -> int:
    cols = ["strategy", "symbol", "side", "qty", "entry_price", "entry_time", "stop", "target",
            "risk_per_share", "extreme", "reason", "meta"]
    with conn() as c:
        cur = c.execute(f"INSERT INTO positions({','.join(cols)}) VALUES({','.join('?' * len(cols))})",
                        [p.get(k) for k in cols])
        return cur.lastrowid


def update_position(pid: int, **fields):
    if not fields:
        return
    sets = ",".join(f"{k}=?" for k in fields)
    with conn() as c:
        c.execute(f"UPDATE positions SET {sets} WHERE id=?", [*fields.values(), pid])


def delete_position(pid: int):
    with conn() as c:
        c.execute("DELETE FROM positions WHERE id=?", (pid,))


def insert_trade(t: dict):
    cols = ["strategy", "symbol", "side", "qty", "entry_price", "entry_time", "exit_price", "exit_time",
            "pnl", "r_multiple", "commission", "entry_reason", "exit_reason"]
    with conn() as c:
        c.execute(f"INSERT INTO trades({','.join(cols)}) VALUES({','.join('?' * len(cols))})",
                  [t.get(k) for k in cols])


def recent_trades(strategy, n):
    with conn() as c:
        return [dict(r) for r in c.execute(
            "SELECT * FROM trades WHERE strategy=? ORDER BY id DESC LIMIT ?", (strategy, n)).fetchall()]


def insert_equity(ts, sleeve, cash, pos_value, equity):
    with conn() as c:
        c.execute("INSERT INTO equity VALUES(?,?,?,?,?)", (ts, sleeve, cash, pos_value, equity))
