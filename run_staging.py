#!/usr/bin/env python3
"""
🚀 SOFÍA AI AGENCY - STAGING LOCAL LAUNCHER (Uvicorn + Ngrok)
Ejecuta el servidor FastAPI en modo desarrollo y levanta el túnel seguro de Ngrok.
"""

import os
import sys
import time
import signal
import subprocess
import urllib.request
import json
import argparse

def get_ngrok_url():
    """Consulta la API local de ngrok (puerto 4040) para obtener la URL pública asignada."""
    api_url = "http://127.0.0.1:4040/api/tunnels"
    for _ in range(20):
        try:
            req = urllib.request.Request(api_url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=2) as response:
                if response.status == 200:
                    data = json.loads(response.read().decode())
                    tunnels = data.get("tunnels", [])
                    for tunnel in tunnels:
                        public_url = tunnel.get("public_url", "")
                        if public_url.startswith("https://"):
                            return public_url
        except Exception:
            pass
        time.sleep(0.5)
    return None

def main():
    parser = argparse.ArgumentParser(description="Launcher para ambiente Staging Local con Ngrok")
    parser.add_argument("--db", choices=["local", "cloud"], default="local",
                        help="Base de datos a utilizar: 'local' (SQLite staging_local.db aislada) o 'cloud' (Render PostgreSQL)")
    parser.add_argument("--port", type=int, default=8000, help="Puerto local para Uvicorn (defecto: 8000)")
    parser.add_argument("--enable-cron", action="store_true", help="Habilitar el cron worker de citas localmente")
    args = parser.parse_args()

    # Configuración de variables de entorno para Staging
    env = os.environ.copy()
    env["ENVIRONMENT"] = "staging"
    env["ENABLE_CRON_WORKER"] = "true" if args.enable_cron else "false"

    if args.db == "local":
        db_path = os.path.abspath("staging_local.db")
        env["DATABASE_URL"] = f"sqlite:///{db_path}"
        db_label = f"SQLite local aislado ({db_path})"
    else:
        db_label = "PostgreSQL en la Nube (Render)"

    # Buscar ngrok
    ngrok_bin = "/snap/bin/ngrok"
    if not os.path.exists(ngrok_bin):
        ngrok_bin = "ngrok"

    print("\n" + "=" * 65)
    print(" 🚀 INICIANDO AMBIENTE STAGING (SOFÍA AI AGENCY)")
    print("=" * 65)
    print(f" • Rama Git:       staging")
    print(f" • Base de Datos:  {db_label}")
    print(f" • Cron Worker:    {'Activo' if args.enable_cron else 'Desactivado (evita colisiones con Render)'}")
    print(f" • Puerto:         {args.port}")
    print("-" * 65)

    # Iniciar Uvicorn
    python_bin = sys.executable
    uvicorn_cmd = [
        python_bin, "-m", "uvicorn", "main:app",
        "--host", "127.0.0.1",
        "--port", str(args.port),
        "--reload"
    ]
    
    print("⏳ Iniciando servidor Uvicorn...")
    uvicorn_proc = subprocess.Popen(uvicorn_cmd, env=env)

    # Iniciar Ngrok
    print("⏳ Conectando túnel seguro con Ngrok...")
    ngrok_cmd = [ngrok_bin, "http", str(args.port), "--log=stdout", "--log-level=warn"]
    ngrok_proc = subprocess.Popen(ngrok_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def cleanup(signum=None, frame=None):
        print("\n\n🛑 Deteniendo ambiente Staging...")
        try:
            ngrok_proc.terminate()
            uvicorn_proc.terminate()
            ngrok_proc.wait(timeout=3)
            uvicorn_proc.wait(timeout=3)
        except Exception:
            pass
        print("✅ Servidor local y túnel Ngrok cerrados correctamente.")
        sys.exit(0)

    signal.signal(signal.SIGINT, cleanup)
    signal.signal(signal.SIGTERM, cleanup)

    # Esperar URL de Ngrok
    public_url = get_ngrok_url()

    print("\n" + "=" * 65)
    print(" 🎉 ¡AMBIENTE STAGING LISTO Y CONECTADO A INTERNET!")
    print("=" * 65)
    if public_url:
        print(f" 🌐 URL Pública Ngrok: \033[1;32m{public_url}\033[0m")
        print(f" 📲 Webhook WhatsApp:   \033[1;36m{public_url}/api/v1/webhook\033[0m")
        print(f" 🔑 Token de Verif:     \033[1;33msofia_meta_secret_token_2026\033[0m")
    else:
        print(" ⚠️  No se pudo detectar la URL de Ngrok en puerto 4040. Verificá si ngrok está corriendo.")

    print(f" 📊 Monitor Ngrok (en vivo):  http://127.0.0.1:4040")
    print(f" 📑 Swagger API Docs:         http://127.0.0.1:{args.port}/docs")
    print("=" * 65)
    print("💡 Presioná Ctrl + C en cualquier momento para detener el servidor.\n")

    # Mantener el proceso vivo hasta Ctrl+C
    try:
        uvicorn_proc.wait()
    except KeyboardInterrupt:
        cleanup()

if __name__ == "__main__":
    main()
