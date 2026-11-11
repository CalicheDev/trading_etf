"""Indicadores con la misma definicion que TradingView (RSI y ATR con suavizado de Wilder)."""
import numpy as np
import pandas as pd


def ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False).mean()


def sma(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(n).mean()


def rma(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(alpha=1.0 / n, adjust=False).mean()


def rsi(close: pd.Series, n: int) -> pd.Series:
    d = close.diff()
    up = rma(d.clip(lower=0), n)
    dn = rma((-d).clip(lower=0), n)
    rs = up / dn.replace(0, np.nan)
    out = 100 - 100 / (1 + rs)
    return out.fillna(100.0).where(dn != 0, 100.0)


def atr(df: pd.DataFrame, n: int) -> pd.Series:
    prev = df["Close"].shift()
    tr = pd.concat([df["High"] - df["Low"], (df["High"] - prev).abs(), (df["Low"] - prev).abs()], axis=1).max(axis=1)
    return rma(tr, n)


def session_vwap(df: pd.DataFrame) -> pd.Series:
    """VWAP que se reinicia cada sesion (indice con zona horaria de NY)."""
    hlc3 = (df["High"] + df["Low"] + df["Close"]) / 3
    day = df.index.date
    pv = (hlc3 * df["Volume"]).groupby(day).cumsum()
    vv = df["Volume"].groupby(day).cumsum()
    return pv / vv.replace(0, np.nan)
