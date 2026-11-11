"""Configuracion del bot. Todos los parametros de la estrategia y del riesgo estan aqui."""
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "bot.db"
EVENTS_FILE = BASE_DIR / "events.csv"
LOG_FILE = BASE_DIR / "bot.log"

TZ = "America/New_York"

# ----- Capital (simulacion) -----
INITIAL_CAPITAL = 5000.0
SLEEVES = {                     # capital asignado a cada estrategia
    "intraday": 1500.0,
    "rotation": 2500.0,
    "rsi2": 500.0,
    "donchian": 500.0,
}

# ----- Costes simulados -----
COMMISSION_PER_SHARE = 0.005
SLIPPAGE_PCT = 0.0002           # 2 pb por lado en ordenes de mercado y stops

# ----- Riesgo global -----
RISK_INTRADAY = 0.005           # 0.5% del capital total por operacion
RISK_SWING = 0.0075             # 0.75%
MAX_OPEN_RISK = 0.04            # 4% del capital
DAILY_LOSS_LIMIT = 0.02         # -2% -> no mas entradas hoy
WEEKLY_LOSS_LIMIT = 0.04        # -4% -> no mas entradas esta semana
DD_HALF_SIZE = 0.08             # -8% desde maximo -> tamano al 50%
DD_LONG_ONLY = 0.12             # -12% -> solo rotacion
DD_KILL = 0.15                  # -15% -> kill switch
KILL_SWITCH_DAYS = 14
COOLDOWN_LOSSES = 5             # perdidas consecutivas por estrategia
COOLDOWN_DAYS = 2               # dias habiles de pausa
EVENT_BLACKOUT_MIN = 15         # minutos antes/despues de un evento macro

# ----- Intradia ORB / VWAP (15m) -----
INTRADAY_SYMBOLS = ["NVDA", "AAPL", "QQQ", "SPY"]
INTRADAY_FRACTIONAL = False
EMA_LEN = 55
RSI_LEN = 14
ATR_LEN = 14
VOL_MULT = 1.2
ATR_STOP = 2.0
RR = 1.5
MAX_TRADES_PER_DAY = 3          # por simbolo
ENTRY_START = "09:45"
ENTRY_END = "15:30"
FLATTEN_AT = "15:55"

# ----- Swing RSI(2) -----
RSI2_SYMBOLS = ["SPY", "QQQ"]   # solo una posicion a la vez (estan correlacionados)
RSI2_ENTRY = 10
RSI2_EXIT = 70
RSI2_MAX_DAYS = 7
RSI2_ATR_STOP = 3.0

# ----- Swing oro Donchian (solo largos) -----
DONCHIAN_SYMBOL = "GLD"
DONCHIAN_ENTRY = 20
DONCHIAN_EXIT = 10
DONCHIAN_TREND = 100
DONCHIAN_ATR_LEN = 20
DONCHIAN_ATR_STOP = 2.5
DONCHIAN_ATR_TRAIL = 3.0
DONCHIAN_MAX_DAYS = 10

# ----- Rotacion mensual de ETF -----
ROTATION_UNIVERSE = ["SPY", "QQQ", "IWM", "EFA", "EEM", "IEF", "GLD", "XLE"]
ROTATION_CASH = "BIL"
ROTATION_TOP_N = 3
ROTATION_SMA_MONTHS = 10
ROTATION_FRACTIONAL = True
ROTATION_MIN_DRIFT = 0.05
ROTATION_ENTER_ON_START = True  # si no hay posiciones, entra con la senal del ultimo cierre de mes

# ----- Horario del bot -----
DAILY_DECISION_TIME = "15:50"   # swing y rotacion deciden con el precio de las 15:50 (aprox. cierre)
LOOP_MINUTES = 15
