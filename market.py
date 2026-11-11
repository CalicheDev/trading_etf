"""Calendario de NYSE: dias habiles, horario (incluye medias sesiones) y ultimo dia habil del mes."""
from datetime import date, datetime, timedelta
from functools import lru_cache
from zoneinfo import ZoneInfo

import pandas as pd
import pandas_market_calendars as mcal

from config import TZ

NY = ZoneInfo(TZ)
_cal = mcal.get_calendar("NYSE")


@lru_cache(maxsize=4)
def _schedule(year: int, month: int) -> pd.DataFrame:
    start = date(year, month, 1) - timedelta(days=7)
    end = date(year + (month == 12), month % 12 + 1, 1) + timedelta(days=7)
    return _cal.schedule(start_date=start, end_date=end)


def session(d: date) -> tuple[datetime, datetime] | None:
    s = _schedule(d.year, d.month)
    key = pd.Timestamp(d)
    if key not in s.index:
        return None
    row = s.loc[key]
    return row["market_open"].tz_convert(NY).to_pydatetime(), row["market_close"].tz_convert(NY).to_pydatetime()


def is_last_trading_day_of_month(d: date) -> bool:
    s = _schedule(d.year, d.month)
    days = [ts.date() for ts in s.index if ts.month == d.month and ts.year == d.year]
    return bool(days) and d == days[-1]


def next_session_open(now: datetime) -> datetime:
    d = now.date()
    for _ in range(10):
        sess = session(d)
        if sess and sess[1] > now:
            return max(sess[0], now)
        d += timedelta(days=1)
    return now + timedelta(hours=12)
