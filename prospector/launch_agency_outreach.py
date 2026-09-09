"""
Dispatcher to start outreach with Sofía to pending AI SDR Agency prospects.
Includes dry-run mode, limit count, and safety delays between WhatsApp dispatches.
"""
import os
import sys
import time
import argparse
import asyncio
from datetime import datetime

# Add project root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.database.database import SessionLocal
from app.database.models.prospect import Prospect
from app.services import whatsapp_service

async def launch_outreach(limit: int = 5, dry_run: bool = False, delay_seconds: int = 15):
    db = SessionLocal()
    pending_leads = db.query(Prospect).filter(
        Prospect.campaign == "ai_agency",
        Prospect.status == "pending"
    ).limit(limit).all()
    
    if not pending_leads:
        print("ℹ️ No hay prospectos pendientes en la campaña 'ai_agency'.")
        db.close()
        return

    print("=" * 80)
    print("🚀 LANZADOR DE PROSPECCIÓN WHATSAPP (Sofía SDR Agency)")
    print(f"🎯 Total a procesar: {len(pending_leads)} empresas | Modo Dry-Run: {dry_run}")
    print("=" * 80)

    for idx, lead in enumerate(pending_leads, 1):
        clean_phone = lead.phone
        clean_company = lead.name.strip() if lead.name else "la empresa"
        pitch = f"Hola buenas! ¿Este es el WhatsApp de {clean_company}? Disculpá la molestia."

        print(f"\n[{idx}/{len(pending_leads)}] 🏢 {lead.name} ({lead.city})")
        print(f"   📱 Teléfono: +{clean_phone} [{lead.business_type}]")
        
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
    args = parser.parse_args()

    asyncio.run(launch_outreach(limit=args.count, dry_run=args.dry_run, delay_seconds=args.delay))
