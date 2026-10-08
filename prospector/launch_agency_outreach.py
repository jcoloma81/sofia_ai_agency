"""
Dispatcher to start outreach with Sofía to pending AI SDR Agency prospects.
Includes dry-run mode, limit count, and safety delays between WhatsApp dispatches.
"""
import os
import sys
import time
import argparse
import asyncio
import json
from datetime import datetime

# Add project root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.database.database import SessionLocal
from app.database.models.prospect import Prospect
from app.services import whatsapp_service

TEMPLATES_FILE = os.path.join(os.path.dirname(__file__), "pitch_templates.json")

def load_pitch_templates():
    if os.path.exists(TEMPLATES_FILE):
        try:
            with open(TEMPLATES_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"⚠️ Error cargando plantillas: {e}")
    return []

def get_template_by_id(template_id: str):
    templates = load_pitch_templates()
    for t in templates:
        if str(t.get("id")) == str(template_id):
            return t
    return None

RUBRO_TO_TEMPLATE_ID = {
    "gimnasio": "1",
    "gym": "1",
    "fitness": "1",
    "taller": "2",
    "mecanico": "2",
    "lubricentro": "2",
    "veterinaria": "3",
    "veterinario": "3",
    "petshop": "3",
    "optica": "4",
    "medico": "5",
    "clinica": "5",
    "consultorio": "5",
    "odontologia": "5",
    "distribuidora": "6",
    "mayorista": "6",
    "ferreteria": "6",
    "corralon": "6",
    "bulonera": "6",
    "repuestos": "6",
    "comercio": "6",
}

async def launch_outreach(limit: int = 5, dry_run: bool = False, delay_seconds: int = 15, template_id: str = "1", auto_rubro: bool = False, rubro_filter: str = None):
    db = SessionLocal()
    query = db.query(Prospect).filter(
        Prospect.campaign == "ai_agency",
        Prospect.status == "pending"
    )
    if rubro_filter:
        query = query.filter(Prospect.business_type.ilike(f"%{rubro_filter}%"))

    pending_leads = query.limit(limit).all()
    
    if not pending_leads:
        print("ℹ️ No hay prospectos pendientes en la campaña 'ai_agency' que coincidan con el filtro.")
        db.close()
        return

    print("=" * 80)
    print("🚀 LANZADOR DE PROSPECCIÓN WHATSAPP (Sofía SDR Agency)")
    print(f"🎯 Total a procesar: {len(pending_leads)} empresas | Modo Dry-Run: {dry_run} | Template base: #{template_id} (Auto-rubro: {auto_rubro})")
    print("=" * 80)

    templates_cache = {t["id"]: t for t in load_pitch_templates()}
    fallback_template = templates_cache.get(template_id) or templates_cache.get("1") or {
        "cuerpo": "Hola buenas! ¿Este es el WhatsApp de {{nombre}}? Disculpá la molestia."
    }

    for idx, lead in enumerate(pending_leads, 1):
        clean_phone = lead.phone
        clean_company = lead.name.strip() if lead.name else "la empresa"
        
        selected_tpl = fallback_template
        if auto_rubro:
            btype = (lead.business_type or "").lower()
            matched_id = None
            for key, tid in RUBRO_TO_TEMPLATE_ID.items():
                if key in btype:
                    matched_id = tid
                    break
            if matched_id and matched_id in templates_cache:
                selected_tpl = templates_cache[matched_id]

        pitch = selected_tpl["cuerpo"].replace("{{nombre}}", clean_company)

        print(f"\n[{idx}/{len(pending_leads)}] 🏢 {lead.name} ({lead.city})")
        print(f"   📱 Teléfono: +{clean_phone} [{lead.business_type}] — Plantilla: {selected_tpl.get('nombre', 'Default')}")
        
        if dry_run:
            print("   🧪 [DRY RUN] Mensaje que se enviaría:")
            print("   " + "\n   ".join(pitch.split("\n")[:4]) + "\n   ...")
        else:
            print("   📤 Enviando WhatsApp vía Gateway...")
            sent = await whatsapp_service.send_whatsapp_message(to_phone=clean_phone, text=pitch)
            if sent:
                lead.status = "contacted"
                lead.updated_at = datetime.utcnow()
                lead.conversation_history = f'[{{"sender": "ai", "text": "{pitch}", "timestamp": "{datetime.utcnow().isoformat()}"}}]'
                db.commit()
                print(f"   ✅ MENSAJE ENVIADO Y REGISTRADO EN BD.")
            else:
                print(f"   ❌ ERROR al enviar mensaje a +{clean_phone}.")

            if idx < len(pending_leads):
                print(f"   ⏳ Esperando {delay_seconds} segundos antes del siguiente envío de seguridad anti-spam...")
                await asyncio.sleep(delay_seconds)

    db.close()
    print("\n" + "=" * 80)
    print(f"🎉 LOTE COMPLETADO. Sofía queda atenta en WhatsApp para responder a quienes contesten.")
    print("=" * 80)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Launch outreach for pending agency leads")
    parser.add_argument("--count", type=int, default=5, help="Number of leads to contact")
    parser.add_argument("--dry-run", action="store_true", help="Simulate without actually sending WhatsApp messages")
    parser.add_argument("--delay", type=int, default=15, help="Seconds between messages")
    parser.add_argument("--template-id", type=str, default="1", help="Template ID from pitch_templates.json (1=Rompehielos, 2=Gym, 3=Taller, 4=Vet, 5=Optica, 6=Salud, 7=B2B)")
    parser.add_argument("--auto-rubro", action="store_true", help="Automatically select template based on lead business_type")
    parser.add_argument("--rubro", type=str, default=None, help="Filter leads by business_type (e.g. gym, taller, veterinaria, optica, distribuidora)")
    args = parser.parse_args()

    asyncio.run(launch_outreach(
        limit=args.count,
        dry_run=args.dry_run,
        delay_seconds=args.delay,
        template_id=args.template_id,
        auto_rubro=args.auto_rubro,
        rubro_filter=args.rubro
    ))
