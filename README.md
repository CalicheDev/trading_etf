# Bot de trading (simulación) + dashboard

Bot en Python que consulta el mercado cada 15 minutos en horario de NYSE, aplica las 4 estrategias validadas
y **simula** las órdenes con un capital de 5,000 USD. No envía órdenes a ningún broker.

## Cómo usarlo

1. Doble clic en **`run_bot.bat`**: arranca el bot. Deja la ventana abierta; el PC debe estar encendido en horario de mercado.
2. Doble clic en **`run_dashboard.bat`**: abre el dashboard en el navegador (http://localhost:8501). Se actualiza solo cada 60 s.

Otras opciones (desde una terminal en esta carpeta):

```
.venv\Scripts\python bot.py --once    # un solo ciclo
.venv\Scripts\python bot.py --reset   # borra la simulación y empieza de cero
```

## Qué hace y cuándo

| Estrategia | Capital | Cuándo decide | Entrada | Salida |
|---|---|---|---|---|
| Intradía ORB/VWAP (NVDA, AAPL, QQQ, SPY) | 1,500 | Cada vela de 15 min, 9:45–15:30 | ORB: cierre fuera del rango de los primeros 15 min, del lado de la EMA55, RSI > 55 (< 45 en cortos). VWAP: cruce a favor de la EMA55 con pendiente y RSI > 50 (< 50 en cortos). Volumen > 1.2× media | Stop 2×ATR, objetivo 3×ATR (1.5R), cierre 5 min antes del final de la sesión |
| Swing RSI(2) (SPY o QQQ) | 500 | 15:50 | Cierre > SMA200 y RSI(2) < 10 | Cierre > SMA5, RSI(2) > 70, 7 días o stop 3×ATR |
| Swing oro Donchian (GLD, solo largos) | 500 | 15:50 | Cierre > máximo de 20 días y > SMA100 | Trailing 3×ATR(20), cierre < mínimo de 10 días, o 10 días sin +1R |
| Rotación de ETF | 2,500 | 15:50 del último día hábil del mes | Top 3 por media de retornos 3/6/12 meses y sobre su SMA de 10 meses; si no, efectivo (BIL) | Rebalanceo mensual |

Reglas de riesgo: 0.5% de riesgo intradía y 0.75% en swing sobre el capital total; riesgo abierto ≤ 4%;
pérdida diaria −2% y semanal −4%; drawdown −8% → tamaño al 50%, −12% → solo rotación, −15% → kill switch de 14 días;
5 pérdidas seguidas en una estrategia → cooldown de 2 días hábiles; sin entradas cerca de eventos de `events.csv`.

Todos los parámetros están en `config.py`.

## Eventos macro

Edita `events.csv` (hora de Nueva York) con las fechas de FOMC, CPI y NFP. Viene con NFP del 4-dic-2026 y FOMC del
9-dic-2026; **verifica y añade el resto** (calendarios de la Fed y del BLS).

## Supuestos de la simulación

- Datos de Yahoo Finance (gratuitos, con posible retraso de ~15 min). El volumen de las velas más recientes puede
  llegar incompleto, así que el filtro de volumen puede diferir del de TradingView.
- Entradas al último precio con 2 pb de slippage; comisión de 0.005 USD por acción.
- Stops comprobados con los mínimos y máximos de las velas; si en la misma vela se tocan stop y objetivo, cuenta el stop.
- Swing y rotación usan el precio de las 15:50 como aproximación al cierre.
- Si el bot está apagado, no gestiona posiciones; al volver, revisa los stops con las velas pasadas.

## Archivos

`bot.py` bucle principal · `strategies/` lógica de cada estrategia · `risk.py` reglas de riesgo ·
`portfolio.py` broker simulado · `market.py` calendario NYSE · `dashboard.py` panel · `bot.db` datos · `bot.log` registro.

## Desplegar en un VPS con Docker (siempre activo)

Requiere Docker y el plugin `docker compose` instalados en el VPS.

```
git clone <tu-repo> trading-bot   # o sube la carpeta por scp/sftp (sin .venv ni __pycache__)
cd trading-bot
docker compose up -d --build
```

Esto arranca dos contenedores con reinicio automático (`restart: unless-stopped`), también tras
reiniciar el VPS si Docker está habilitado como servicio (`systemctl enable docker`):

- `trading-bot`: el bucle del bot, corriendo de forma continua.
- `trading-dashboard`: el panel en `http://<ip-del-vps>:8501`.

`bot.db`, `bot.log` y `events.csv` se leen y escriben directamente en la carpeta del proyecto (montada
como volumen), así que persisten entre reinicios y son compartidos por ambos contenedores.

Comandos útiles:

```
docker compose logs -f bot        # ver el registro en vivo
docker compose restart bot        # reiniciar solo el bot
docker compose down                # detener todo
docker compose up -d --build       # reconstruir tras cambiar el código o requirements.txt
```

El dashboard no tiene autenticación: si el VPS es accesible públicamente, restringe el puerto 8501
con el firewall a tu IP, o ponlo detrás de un reverse proxy (nginx/Caddy) con contraseña, en vez de
exponerlo directamente a internet.
