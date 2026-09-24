@echo off
REM Arranca la demo de Montelier en Windows (doble clic o "arrancar.bat")
cd /d "%~dp0"
if not exist .venv (
  echo Preparando el entorno, solo la primera vez...
  py -3 -m venv .venv || python -m venv .venv
  .venv\Scripts\python -m pip install --quiet --upgrade pip
  .venv\Scripts\python -m pip install --quiet -r requirements.txt
)
if not exist .env (
  copy .env.example .env >nul
  echo AVISO: se ha creado .env. Pon tu ANTHROPIC_API_KEY en el para que funcione el Asistente.
)
.venv\Scripts\python app.py
