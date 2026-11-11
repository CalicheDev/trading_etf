@echo off
cd /d "%~dp0"
if not exist .venv (
  echo Creando entorno e instalando dependencias...
  py -3.12 -m venv .venv
  .venv\Scripts\python -m pip install -q -r requirements.txt
)
.venv\Scripts\python -m streamlit run dashboard.py --server.headless false --browser.gatherUsageStats false
