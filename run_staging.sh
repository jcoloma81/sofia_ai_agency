#!/usr/bin/env bash
# 🚀 SOFÍA AI AGENCY - Ejecutable de Staging Local
set -e

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
cd "$DIR"

# Activar venv si existe
if [ -d "venv" ]; then
    PYTHON_EXEC="venv/bin/python"
elif [ -d ".venv" ]; then
    PYTHON_EXEC=".venv/bin/python"
else
    PYTHON_EXEC="python3"
fi

exec "$PYTHON_EXEC" run_staging.py "$@"
