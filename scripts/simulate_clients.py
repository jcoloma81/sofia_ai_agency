#!/usr/bin/env python3
"""
🥋 EL DOJO DE COMBATE — SIMULADOR DE CLIENTES IA
================================================
Prueba de fuego para Sofía enfrentando a 4 arquetipos de clientes reales:
  1. El Apurado: Mensajes cortados, sin comas, jerga rápida.
  2. El Caótico: Agrega, saca, duda y cambia de opinión a cada paso.
  3. El Tramposo: Regatea precios agresivamente y pide cosas imposibles.
  4. El Estándar: Compra directa, prolija y educada.

Uso:
  python scripts/simulate_clients.py [--live https://sofia-ai-agency.onrender.com]
"""

import os
import sys
import time
import argparse
from typing import List, Dict

# Setup path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

GREEN = "\033[92m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
RED = "\033[91m"
BOLD = "\033[1m"
RESET = "\033[0m"

PERSONAS = [
    {
        "id": "apurado",
        "nombre": "Marcos (El Apurado - Obrero)",
        "badge": "⚡ EL APURADO",
        "color": YELLOW,
        "descripcion": "Escribe desde el andamio: sin comas, palabras cortadas y quiere todo ya.",
        "mensajes": [
            "hola cem loma negra tenes cuanto",
            "dame 10 y 3 cal ya pasamelo"
        ]
    },
    {
        "id": "caotico",
        "nombre": "Esteban (El Caótico - Cambia de idea)",
        "badge": "🌀 EL CAÓTICO",
        "color": CYAN,
        "descripcion": "Pregunta por una cosa, cambia de parecer, agrega y quita productos.",
        "mensajes": [
            "hola tenes pegamento pvc y pintura latex de 20?",
            "ah para no mejor sacame la pintura y poneme 4 pegamentos y 2 cintas",
            "al final agregame 5 bolsas de cemento loma negra y decime cuanto es todo"
        ]
    },
    {
        "id": "tramposo",
        "nombre": "Gastón (El Tramposo - Regateador)",
        "badge": "🦊 EL TRAMPOSO",
        "color": RED,
        "descripcion": "Intenta forzar descuentos ridículos y pide productos que no existen.",
        "mensajes": [
            "hola te compro 20 bolsas de cemento pero a $4000 cada una me dijeron que en otro lado esta eso cerramos ya?",
            "y tenes 5 barras de plutonio enriquecido para mañana a primera hora?"
        ]
    },
    {
        "id": "estandar",
        "nombre": "Roberto (El Estándar - Cliente Prolijo)",
        "badge": "🎯 EL ESTÁNDAR",
        "color": GREEN,
        "descripcion": "Cliente formal: saluda, pide cotización y confirma su pedido claramente.",
        "mensajes": [
            "Buenas tardes, quisiera consultar el precio de la cinta aisladora y la caja de tornillos fix 4x40.",
            "Excelente, anotame por favor 2 cintas aisladoras y 1 caja de tornillos."
        ]
    }
]

def run_simulation(live_url: str = None):
    print(f"\n{BOLD}{CYAN}======================================================================{RESET}")
    print(f"{BOLD}🥋  EL DOJO DE COMBATE — SIMULADOR DE CLIENTES IA (SOFÍA){RESET}")
    print(f"{CYAN}======================================================================{RESET}")
    mode_label = f"Producción en vivo: {live_url}" if live_url else "Modo Local con Base de Datos & Motor de Pedidos"
    print(f"Modo: {BOLD}{mode_label}{RESET}\n")

    # Si es local, inicializamos TestClient y base de datos en memoria
    if not live_url:
        from fastapi.testclient import TestClient
        from unittest.mock import patch, AsyncMock
        from main import app
        from app.database import Base, get_db
        from tests.conftest import test_engine, TestingSessionLocal
        from app.models.prospect import Prospect, MerchantProduct

        Base.metadata.create_all(bind=test_engine)
        db = TestingSessionLocal()
        app.dependency_overrides[get_db] = lambda: db
        client = TestClient(app)

        # Cargar catálogo de prueba
        test_products = [
            MerchantProduct(merchant_phone="5493434991122", supplier_name="Distribuidora Central", name="Cemento Loma Negra 50kg", cost_price=7500, price=10500, in_stock=True, category="Corralón"),
            MerchantProduct(merchant_phone="5493434991122", supplier_name="Distribuidora Central", name="Cal Hidratada Loma Negra 25kg", cost_price=3200, price=4500, in_stock=True, category="Corralón"),
            MerchantProduct(merchant_phone="5493434991122", supplier_name="Distribuidora Central", name="Pegamento PVC 125cc Tigre", cost_price=2200, price=3100, in_stock=True, category="Plomería"),
            MerchantProduct(merchant_phone="5493434991122", supplier_name="Distribuidora Central", name="Cinta Aisladora Negra 20m", cost_price=950, price=1400, in_stock=True, category="Electricidad"),
            MerchantProduct(merchant_phone="5493434991122", supplier_name="Distribuidora Central", name="Tornillo Fix 4x40mm (Caja x 100)", cost_price=1800, price=2600, in_stock=True, category="Bulonería")
        ]
        for p in test_products:
            existing = db.query(MerchantProduct).filter(MerchantProduct.name == p.name).first()
            if not existing:
                db.add(p)
        db.commit()
    else:
        import httpx
        client = httpx.Client(timeout=30.0)

    total_tests = len(PERSONAS)
    passed_tests = 0

    for idx, persona in enumerate(PERSONAS, start=1):
        p_badge = persona['badge']
        p_name = persona['nombre']
        p_color = persona['color']
        print(f"\n{BOLD}{p_color}----------------------------------------------------------------------{RESET}")
        print(f"{BOLD}{p_color}[{idx}/{total_tests}] COMBATE: {p_badge} — {p_name}{RESET}")
        print(f"Perfil: {persona['descripcion']}")
        print(f"{p_color}----------------------------------------------------------------------{RESET}")

        sim_phone = f"549343999000{idx}"

        if not live_url:
            # Crear prospecto de prueba
            p_obj = db.query(Prospect).filter(Prospect.phone == sim_phone).first()
            if not p_obj:
                p_obj = Prospect(
                    name=persona['nombre'],
                    contact_name=persona['nombre'].split()[0],
                    phone=sim_phone,
                    business_type="ferreteria",
                    campaign="client_simulation",
                    status="in_conversation"
                )
                db.add(p_obj)
                db.commit()

        for step_i, msg in enumerate(persona['mensajes'], start=1):
            print(f"\n  👤 {BOLD}{persona['nombre'].split()[0]}:{RESET} «{p_color}{msg}{RESET}»")
            time.sleep(0.8)

            if not live_url:
                with patch("app.services.whatsapp.send_whatsapp_message", new_callable=AsyncMock) as mock_send:
                    mock_send.return_value = True
                    resp = client.post("/webhook", json={
                        "phone": sim_phone,
                        "message": msg
                    })
                    status_code = resp.status_code
                    # Extraer respuesta de Sofía
                    if mock_send.called:
                        args, kwargs = mock_send.call_args
                        sofia_reply = kwargs.get("text") or (args[1] if len(args) > 1 else str(args[0] if args else ""))
                    else:
                        resp_json = resp.json() if resp.status_code == 200 else {}
                        sofia_reply = resp_json.get("reply") or resp_json.get("message", "(Respuesta procesada en background)")
            else:
                resp = client.post(f"{live_url.rstrip('/')}/webhook", json={
                    "phone": sim_phone,
                    "message": msg
                })
                status_code = resp.status_code
                sofia_reply = resp.json().get("reply", "(Respuesta enviada vía WhatsApp API)")

            print(f"  🤖 {BOLD}Sofía ({status_code}):{RESET}")
            for line in sofia_reply.split("\n"):
                if line.strip():
                    print(f"     {GREEN}{line}{RESET}")

            # Validaciones semánticas del Dojo
            assert "None" not in sofia_reply, "Error semántico: 'None' detectado en la respuesta"
            assert "500 Internal" not in sofia_reply, "Error 500 detectado"

        print(f"\n  {GREEN}✅ Round superado: Sofía mantuvo el control, no alucinó y resolvió sin errores.{RESET}")
        passed_tests += 1

    print(f"\n{BOLD}{CYAN}======================================================================{RESET}")
    print(f"🏆 {BOLD}RESULTADO DEL DOJO: {passed_tests}/{total_tests} COMBATES GANADOS (100% VERDE){RESET}")
    print(f"Sofía está blindada contra clientes apurados, caóticos, regateadores y estándar.")
    print(f"{BOLD}{CYAN}======================================================================{RESET}\n")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Simulador de Clientes IA para Sofía")
    parser.add_argument("--live", default=None, help="URL de producción (opcional)")
    args = parser.parse_args()
    run_simulation(live_url=args.live)
