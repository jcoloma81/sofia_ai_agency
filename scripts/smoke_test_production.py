#!/usr/bin/env python3
"""
🛡️ CENTINELA DE PRODUCCIÓN — SOFÍA AI AGENCY
Verificación en caliente post-despliegue en 3 segundos.
Uso:
    python scripts/smoke_test_production.py [--url https://tu-servicio.onrender.com]
"""

import sys
import time
import argparse
import requests

# ANSI Color Codes
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
BOLD = "\033[1m"
RESET = "\033[0m"

def run_smoke_test(base_url: str):
    base_url = base_url.rstrip("/")
    print(f"\n{BOLD}{CYAN}============================================================{RESET}")
    print(f"{BOLD}🛡️  CENTINELA DE PRODUCCIÓN — SOFÍA AI AGENCY{RESET}")
    print(f"{CYAN}============================================================{RESET}")
    print(f"🌐 Servidor Objetivo: {BOLD}{base_url}{RESET}\n")

    all_passed = True
    start_total = time.time()

    # 1. Health & Database Check
    print(f"🔍 [1/3] Verificando Servidor y Base de Datos (/health)...")
    try:
        t0 = time.time()
        resp_health = requests.get(f"{base_url}/health", timeout=60)
        lat_health = int((time.time() - t0) * 1000)

        if resp_health.status_code == 200:
            h_data = resp_health.json()
            db_status = h_data.get("database", "unknown")
            if db_status == "connected":
                print(f"   {GREEN}✅ Servidor Web y PostgreSQL: CONECTADOS Y SALUDABLES ({lat_health} ms){RESET}")
            else:
                print(f"   {RED}❌ Base de Datos: {db_status.upper()} (Error de conexión){RESET}")
                all_passed = False
        else:
            print(f"   {RED}❌ Error HTTP {resp_health.status_code}: {resp_health.text}{RESET}")
            all_passed = False
    except requests.exceptions.Timeout:
        print(f"   {RED}❌ Tiempo de espera agotado (>60s). El servidor podría estar dormido o inaccesible.{RESET}")
        all_passed = False
    except Exception as e:
        print(f"   {RED}❌ Error al conectar: {e}{RESET}")
        all_passed = False

    # 2. Meta WhatsApp Webhook Challenge Verification
    print(f"\n🔍 [2/3] Verificando Portero de WhatsApp Cloud API (/webhook challenge)...")
    try:
        test_challenge = "sofia_sentinel_token_challenge_777"
        verify_token = "sofia_meta_secret_token_2026"
        t0 = time.time()
        resp_hook = requests.get(
            f"{base_url}/webhook",
            params={
                "hub.mode": "subscribe",
                "hub.challenge": test_challenge,
                "hub.verify_token": verify_token
            },
            timeout=15
        )
        lat_hook = int((time.time() - t0) * 1000)
        if resp_hook.status_code == 200 and resp_hook.text.strip() == test_challenge:
            print(f"   {GREEN}✅ Portero de WhatsApp: 100% RECEPTIVO Y VERIFICADO ({lat_hook} ms){RESET}")
        else:
            print(f"   {RED}❌ Portero Webhook no validó el token oficial de Meta. Status: {resp_hook.status_code}{RESET}")
            all_passed = False
    except Exception as e:
        print(f"   {RED}❌ Error verificando webhook: {e}{RESET}")
        all_passed = False

    # 3. Public Web Landing
    print(f"\n🔍 [3/3] Verificando Portal Comercial Web (/)...")
    try:
        t0 = time.time()
        resp_landing = requests.get(f"{base_url}/", timeout=15)
        lat_landing = int((time.time() - t0) * 1000)
        if resp_landing.status_code == 200:
            print(f"   {GREEN}✅ Portal Comercial Web: ONLINE ({lat_landing} ms){RESET}")
        else:
            print(f"   {YELLOW}⚠️ Portal Web devolvió status {resp_landing.status_code}{RESET}")
    except Exception as e:
        print(f"   {YELLOW}⚠️ No se pudo verificar portal web: {e}{RESET}")

    total_time = round(time.time() - start_total, 2)
    print(f"\n{CYAN}------------------------------------------------------------{RESET}")
    if all_passed:
        print(f"{BOLD}{GREEN}🎯 RESULTADO FINAL: PRODUCCIÓN 100% OPERATIVA Y SANA ({total_time}s){RESET}")
        print(f"{BOLD}{GREEN}🚀 Sistema completamente listo para atender clientes y proveedores.{RESET}")
        print(f"{CYAN}============================================================{RESET}\n")
        return 0
    else:
        print(f"{BOLD}{RED}🚨 RESULTADO FINAL: SE DETECTARON FALLOS EN PRODUCCIÓN{RESET}")
        print(f"{BOLD}{RED}Revisar los mensajes rojos antes de operar.{RESET}")
        print(f"{CYAN}============================================================{RESET}\n")
        return 1

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Centinela de Producción de Sofía AI")
    parser.add_argument("--url", default="https://sofia-ai-agency.onrender.com", help="Base URL del servidor")
    args = parser.parse_args()
    sys.exit(run_smoke_test(args.url))
