#!/bin/bash
echo "============================================================"
echo "          SOFIA BRIDGE - CONECTOR PARA EXCEL (LINUX)"
echo "============================================================"
echo ""
echo "Conectando con Sofia en la nube..."

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
cd "$DIR"

if [ ! -f config.json ]; then
    echo "[CONFIGURACION INICIAL]"
    echo "No se encontro config.json. Creando uno por defecto..."
    echo '{"merchant_phone": "5493434991122", "server_url": "https://sofia-ai-agency.onrender.com", "excel_path": "ferreteria_demo.xlsx", "poll_interval": 2}' > config.json
fi

python3 sofia_bridge.py
