#!/usr/bin/env bash
# Arranca la demo de Montelier: crea el entorno la primera vez, prepara la base y abre el servidor.
set -e
cd "$(dirname "$0")"

if [ ! -f .env ]; then
  cp .env.example .env
  echo "Se ha creado el archivo .env: pon tu ANTHROPIC_API_KEY en él (open -e .env) para que funcione el Asistente."
fi

# Busca un Python 3.10 o superior (el de serie en macOS suele ser 3.9)
buscar_python() {
  for candidato in python3.13 python3.12 python3.11 python3.10 python3 \
                   /opt/homebrew/bin/python3 /usr/local/bin/python3 \
                   /Library/Frameworks/Python.framework/Versions/3.1[0-9]/bin/python3; do
    if command -v "$candidato" >/dev/null 2>&1 &&
       "$candidato" -c 'import sys; sys.exit(sys.version_info < (3, 10))' 2>/dev/null; then
      echo "$candidato"
      return 0
    fi
  done
  return 1
}

# Entorno a medias o creado con un Python antiguo: se rehace
if [ -d .venv ] && { [ ! -f .venv/.instalado ] ||
     ! .venv/bin/python -c 'import sys; sys.exit(sys.version_info < (3, 10))' 2>/dev/null; }; then
  rm -rf .venv
fi

if [ ! -d .venv ]; then
  if ! PYTHON=$(buscar_python); then
    echo
    echo "Hace falta Python 3.10 o superior y no lo encuentro (tienes: $(python3 --version 2>&1))."
    echo "Instálalo desde https://www.python.org/downloads/ (botón 'Download Python 3.x')"
    echo "o con Homebrew:  brew install python@3.12"
    echo "Después, vuelve a ejecutar:  ./arrancar.sh"
    exit 1
  fi
  echo "Preparando el entorno con $($PYTHON --version) (solo la primera vez)..."
  "$PYTHON" -m venv .venv
  .venv/bin/pip install --quiet --upgrade pip
  .venv/bin/pip install --quiet -r requirements.txt
  touch .venv/.instalado
fi

exec .venv/bin/python app.py
