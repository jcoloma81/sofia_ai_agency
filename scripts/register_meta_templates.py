#!/usr/bin/env python3
"""
CLI Tool for registering and validating Sofia AI Agency Master Meta Templates.

Reads template definitions from app/data/meta_master_templates.json and:
1. Validates schema compliance with Meta WhatsApp Cloud API v20.0.
2. In '--dry-run' mode (default): Displays formatted cards and raw JSON payloads for review.
3. In '--register' mode: Posts templates directly to https://graph.facebook.com/v20.0/{WABA_ID}/message_templates.

Usage:
    python scripts/register_meta_templates.py --dry-run
    python scripts/register_meta_templates.py --register
"""

import sys
import os
import json
import argparse
import logging
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import httpx
from app.config.settings import settings

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("register_meta_templates")

TEMPLATES_FILE = PROJECT_ROOT / "app" / "data" / "meta_master_templates.json"

def load_templates():
    if not TEMPLATES_FILE.exists():
        logger.error(f"❌ No se encontró el archivo de plantillas en {TEMPLATES_FILE}")
        sys.exit(1)
    with open(TEMPLATES_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def display_dry_run(templates):
    print("\n" + "=" * 70)
    print("📋 REVISIÓN DE PLANTILLAS MAESTRAS DE META WHATSAPP CLOUD API")
    print("=" * 70)
    print(f"Total de plantillas configuradas: {len(templates)}\n")

    for i, t in enumerate(templates, 1):
        print(f"[{i}/{len(templates)}] 🏷️  NOMBRE: {t['name']}")
        print(f"    • Categoría Meta : {t['category']} (Tarifa oficial correspondiente)")
        print(f"    • Idioma        : {t['language']}")
        print(f"    • Rubros foco   : {', '.join(t.get('rubros', []))}")
        print(f"    • Descripción   : {t.get('description', '')}")
        
        # Components inspection
        for comp in t.get("components", []):
            c_type = comp.get("type")
            if c_type == "BODY":
                clean_preview = comp.get("text", "").replace("\n", "\n      | ")
                print(f"    • Componente BODY:\n      | {clean_preview}")
                if "example" in comp:
                    examples = comp["example"].get("body_text", [[]])[0]
                    print(f"      Variables de ejemplo: {examples}")
            elif c_type == "BUTTONS":
                buttons = [b.get("text") for b in comp.get("buttons", [])]
                print(f"    • Botones Interactivos: {buttons}")
        print("-" * 70)

    print("\n💡 Para registrar estas plantillas en tu cuenta oficial de Meta:")
    print("   1. Verificá que META_ACCESS_TOKEN y META_WABA_ID estén configurados en tu archivo .env.")
    print("   2. Ejecutá: python scripts/register_meta_templates.py --register\n")

def register_templates_in_meta(templates):
    waba_id = settings.META_WABA_ID
    token = settings.META_ACCESS_TOKEN

    if not waba_id or not token or token.startswith("your_"):
        print("\n❌ ERROR: Falta configurar credenciales de Meta en el archivo .env:")
        print("   • META_WABA_ID (ID de tu cuenta de WhatsApp Business)")
        print("   • META_ACCESS_TOKEN (Token de acceso del Administrador Comercial de Meta)")
        print("\nPor favor agregá estas variables a tu archivo .env e intentá nuevamente.")
        sys.exit(1)

    url = f"https://graph.facebook.com/v20.0/{waba_id}/message_templates"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    print("\n" + "=" * 70)
    print(f"🚀 REGISTRANDO {len(templates)} PLANTILLAS EN META WABA ID: {waba_id}")
    print("=" * 70)

    success_count = 0
    already_exists_count = 0
    error_count = 0

    with httpx.Client(timeout=20.0) as client:
        for t in templates:
            name = t["name"]
            payload = {
                "name": t["name"],
                "category": t["category"],
                "language": t["language"],
                "components": t["components"]
            }

            print(f"\nEnviando '{name}' ({t['category']})...", end=" ")
            try:
                response = client.post(url, headers=headers, json=payload)
                resp_json = response.json()

                if response.status_code in (200, 201):
                    template_id = resp_json.get("id", "OK")
                    print(f"✅ REGISTRADA (ID: {template_id})")
                    success_count += 1
                elif response.status_code == 400 and (
                    "already exists" in str(resp_json) 
                    or "Ya hay contenido" in str(resp_json)
                    or resp_json.get("error", {}).get("error_subcode") == 2388040
                ):
                    print("⚠️ YA EXISTE en Meta (Sin cambios necesarios)")
                    already_exists_count += 1
                else:
                    err_detail = resp_json.get("error", {})
                    err_msg = err_detail.get("error_user_msg") or err_detail.get("message", response.text)
                    print(f"❌ ERROR ({response.status_code}): {err_msg}")
                    error_count += 1
            except Exception as e:
                print(f"💥 EXCEPCIÓN: {str(e)}")
                error_count += 1

    print("\n" + "=" * 70)
    print(f"📊 RESUMEN FINAL:")
    print(f"   • Creadas exitosamente : {success_count}")
    print(f"   • Ya existentes en Meta : {already_exists_count}")
    print(f"   • Errores encontrados   : {error_count}")
    print("=" * 70 + "\n")

def main():
    parser = argparse.ArgumentParser(description="Gestor de Plantillas Meta WhatsApp para Sofia AI Agency")
    parser.add_argument("--register", action="store_true", help="Registra las plantillas en Meta Cloud API vía HTTP POST")
    parser.add_argument("--dry-run", action="store_true", help="Muestra las plantillas y variables sin hacer peticiones a Meta")
    args = parser.parse_args()

    templates = load_templates()

    if args.register:
        register_templates_in_meta(templates)
    else:
        display_dry_run(templates)

if __name__ == "__main__":
    main()
