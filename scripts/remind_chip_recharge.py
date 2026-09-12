#!/usr/bin/env python3
"""
Automated maintenance reminder script.
Sends a high-priority WhatsApp alert to Javier to recharge Sofia's prepaid line
every 60 days so mobile carriers (Personal/Claro/Movistar) never cancel or recycle it.
"""

import sys
import os
import asyncio
import logging
from datetime import datetime, timezone

# Ensure project root is in python path
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from app.config.settings import settings
from app.services import whatsapp

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

async def main():
    target_phone = settings.WHATSAPP_ALERT_PHONE or "5493434536447"
    agent_phone = settings.WHATSAPP_AGENT_PHONE or "5493435720312"

    logger.info(f"Triggering 60-day SIM recharge maintenance reminder for {agent_phone} -> {target_phone}...")

    reminder_text = (
        f"🔋 *RECORDATORIO DE MANTENIMIENTO: LÍNEA DE SOFÍA* 📱\n\n"
        f"¡Hola Javier! Han transcurrido *60 días* desde la última recarga programada de la línea de Sofía (+{agent_phone}).\n\n"
        f"⚠️ *Acción necesaria:* Hacé una recarga mínima de saldo ($500 a $1.000) a través de Mercado Pago, Home Banking o app de la compañía.\n\n"
        f"💡 *¿Por qué es importante?* Las telefónicas en Argentina reciclan las líneas prepagas inactivas a los 60-90 días. Al recargar saldo garantizás que la línea quede 100% activa a tu nombre y que la API oficial de Meta siga operando sin interrupciones.\n\n"
        f"✅ _Próxima recarga después de esta: dentro de 60 días._"
    )

    try:
        sent = await whatsapp.send_whatsapp_message(to_phone=target_phone, text=reminder_text)
        logger.info(f"WhatsApp maintenance reminder result: {sent}")
    except Exception as err:
        logger.error(f"Error dispatching WhatsApp maintenance reminder: {err}")

if __name__ == "__main__":
    asyncio.run(main())
