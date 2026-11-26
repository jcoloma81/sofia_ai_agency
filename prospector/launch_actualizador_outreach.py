"""
Lanzador de prospección B2B oficial para Actualizador Pro (Meta Cloud API).
Despacha la plantilla aprobada a los comercios cosechados con pausas seguras.
"""
import os
import sys
import time
import argparse
import asyncio
from datetime import datetime, timezone

# Add project root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.database import SessionLocal
from app.models.prospect import Prospect
from app.services import whatsapp
from app.config.settings import settings

async def run_actualizador_campaign(
    limit: int = 15,
    dry_run: bool = False,
    delay_seconds: int = 25,
    template_name: str = "actualizador_comercios_v2"
):
    db = SessionLocal()
    try:
        leads = db.query(Prospect).filter(
            Prospect.campaign == "actualizador_pro",
            Prospect.status == "pending"
        ).order_by(Prospect.id.asc()).limit(limit).all()

        if not leads:
            print("ℹ️ No hay prospectos pendientes en la campaña 'actualizador_pro'.")
            return

        print("=" * 75)
        print("🚀 DESPACHADOR OFICIAL DE PROSPECCIÓN (Actualizador Pro)")
        print(f"🎯 Total a procesar: {len(leads)} comercios")
        print(f"📋 Plantilla Meta: {template_name}")
        print(f"📱 Chip Emisor: {settings.META_PHONE_NUMBER_ID}")
        print(f"⏱️ Intervalo entre envíos: {delay_seconds}s | Modo Dry-Run: {dry_run}")
        print("=" * 75)

        sent_count = 0
        error_count = 0

        for idx, lead in enumerate(leads, 1):
            clean_phone = "".join(filter(str.isdigit, lead.phone or ""))
            print(f"\n[{idx}/{len(leads)}] {lead.name} ({lead.city or 'S/D'}) | Tel: {clean_phone}")

            if dry_run:
                print(f"   [DRY-RUN] Se enviaría plantilla '{template_name}' a {clean_phone}")
                sent_count += 1
                continue

            success = await whatsapp.send_whatsapp_template(
                to_phone=clean_phone,
                template_name=template_name,
                language_code="es_AR"
            )

            if success:
                lead.status = "contacted"
                lead.updated_at = datetime.now(timezone.utc)
                db.commit()
                print(f"   ✅ Plantilla enviada con éxito. Estado actualizado a 'contacted'.")
                sent_count += 1
            else:
                print(f"   ❌ Error al enviar plantilla a {clean_phone}.")
                error_count += 1

            if idx < len(leads) and not dry_run:
                print(f"   ⏳ Esperando {delay_seconds}s para evitar rate-limits de Meta...")
                await asyncio.sleep(delay_seconds)

        print("\n" + "=" * 75)
        print(f"🏁 Campaña finalizada: {sent_count} enviados | {error_count} errores")
        print("=" * 75)

    finally:
        db.close()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Lanzador de prospección Actualizador Pro")
    parser.add_argument("--limit", type=int, default=15, help="Cantidad de comercios a enviar (default: 15)")
    parser.add_argument("--dry-run", action="store_true", help="Simula el envío sin disparar mensajes reales")
    parser.add_argument("--delay", type=int, default=25, help="Segundos entre envíos (default: 25)")
    parser.add_argument("--template", type=str, default="actualizador_comercios_v2", help="Nombre de plantilla Meta")

    args = parser.parse_args()
    asyncio.run(run_actualizador_campaign(
        limit=args.limit,
        dry_run=args.dry_run,
        delay_seconds=args.delay,
        template_name=args.template
    ))
