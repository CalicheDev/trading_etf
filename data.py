"""Datos de mercado gratuitos via Yahoo Finance (pueden venir con ~15 min de retraso)."""
import logging
import time
from datetime import datetime, timedelta

import pandas as pd
import yfinance as yf

from config import TZ

log = logging.getLogger("bot")


def _history(symbol: str, interval: str, period: str, retries: int = 3) -> pd.DataFrame:
    for attempt in range(retries):
        try:
            df = yf.Ticker(symbol).history(interval=interval, period=period, auto_adjust=False, prepost=False)
            if df is not None and not df.empty:
                df = df[["Open", "High", "Low", "Close", "Volume"]].dropna(subset=["Close"])
                if df.index.tz is None:
                    df.index = df.index.tz_localize("UTC")
                df.index = df.index.tz_convert(TZ)
                return df
        except Exception as e:  # red, limite de peticiones, etc.
            log.warning("Fallo descargando %s %s (intento %d): %s", symbol, interval, attempt + 1, e)
        time.sleep(2 * (attempt + 1))
    log.error("Sin datos para %s %s", symbol, interval)
    return pd.DataFrame()


def intraday_15m(symbol: str, now: datetime) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Devuelve (velas cerradas, todas incluida la que se esta formando)."""
    df = _history(symbol, "15m", "30d")
    if df.empty:
        return df, df
    closed = df[df.index + timedelta(minutes=15) <= now]
    return closed, df


def daily(symbol: str, period: str = "3y") -> pd.DataFrame:
    df = _history(symbol, "1d", period)
    if not df.empty:
        df.index = df.index.normalize()
    return df


def last_price(symbol: str) -> float | None:
    df = _history(symbol, "1m", "1d")
    if df.empty:
        df = _history(symbol, "15m", "5d")
    return float(df["Close"].iloc[-1]) if not df.empty else None
