#!/usr/bin/env bash
# Arranca la demo de Montelier: crea el entorno la primera vez, prepara la base y abre el servidor.
set -e
cd "$(dirname "$0")"

if [ ! -d .venv ]; then
  echo "Preparando el entorno (solo la primera vez)..."
  python3 -m venv .venv
  .venv/bin/pip install --quiet --upgrade pip
  .venv/bin/pip install --quiet -r requirements.txt
fi

if [ ! -f .env ]; then
  cp .env.example .env
  echo "AVISO: se ha creado .env. Pon tu ANTHROPIC_API_KEY en él para que funcione el Asistente."
fi

exec .venv/bin/python app.py
