import asyncio
import logging
import re
from typing import Optional, Any, List
import httpx
from datetime import datetime
from app.config.settings import settings
from app.services.alerts import send_email_alert, build_meeting_html_email

logger = logging.getLogger(__name__)

def get_phone_candidates(phone: str) -> List[str]:
    """
    Generates candidate phone numbers to maximize delivery compatibility.
    Specifically handles Argentina variations (+54 9 vs +54 15).
    """
    clean = "".join(filter(str.isdigit, phone))
    candidates = [clean]
    # Argentina mobile with 9: 549 343 4536447 (13 digits) -> 54 343 15 4536447
    if clean.startswith("549") and len(clean) == 13:
        candidates.append(f"54{clean[3:6]}15{clean[6:]}")
    # Argentina mobile with 9: 549 11 12345678 (12 digits) -> 54 11 15 12345678
    elif clean.startswith("549") and len(clean) == 12:
        candidates.append(f"54{clean[3:5]}15{clean[5:]}")
    # Argentina mobile with 15: 54 343 15 4536447 -> 549 343 4536447
    elif clean.startswith("54") and "15" in clean:
        stripped = clean.replace("15", "", 1)
        candidates.append(stripped[:2] + "9" + stripped[2:])
    return candidates

async def send_whatsapp_message(to_phone: str, text: str) -> bool:
    """
    Sends a WhatsApp message via Official Meta WhatsApp Cloud API (Primary Enterprise Gateway),
    or falls back to Whapi.Cloud, or simulation log.
    """
    clean_phone = "".join(filter(str.isdigit, to_phone))

    # 1. Official Meta WhatsApp Cloud API (Primary Enterprise Gateway)
    if settings.META_ACCESS_TOKEN and settings.META_PHONE_NUMBER_ID:
        meta_url = f"https://graph.facebook.com/v20.0/{settings.META_PHONE_NUMBER_ID}/messages"
        meta_headers = {
            "Authorization": f"Bearer {settings.META_ACCESS_TOKEN}",
            "Content-Type": "application/json"
        }
        for target_phone in get_phone_candidates(clean_phone):
            meta_payload = {
                "messaging_product": "whatsapp",
                "recipient_type": "individual",
                "to": target_phone,
                "type": "text",
                "text": {"preview_url": False, "body": text}
            }
            try:
                async with httpx.AsyncClient(timeout=15.0) as client:
                    res = await client.post(meta_url, json=meta_payload, headers=meta_headers)
                    if res.status_code in [200, 201]:
                        logger.info(f"✅ Meta WhatsApp Cloud API message sent successfully to {target_phone}")
                        return True
                    else:
                        logger.warning(f"Meta Cloud API returned status {res.status_code} for {target_phone}: {res.text}")
            except Exception as e:
                logger.error(f"Error calling Meta WhatsApp Cloud API for {target_phone}: {e}")

    # 2. Whapi.Cloud Gateway Fallback
    api_url = settings.WHATSAPP_API_URL
    api_token = settings.WHATSAPP_API_TOKEN

    if not api_url or not api_token:
        logger.info(f"[WHATSAPP SIMULATION] Message to {clean_phone}: {text}")
        return True

    try:
        headers = {
            "Authorization": f"Bearer {api_token}",
            "Content-Type": "application/json",
            "accept": "application/json"
        }

        # Whapi Cloud format
        if "whapi.cloud" in api_url:
            endpoint = f"{api_url.rstrip('/')}/messages/text"
            payload = {
                "to": clean_phone,
                "body": text
            }
        else:
            endpoint = f"{api_url.rstrip('/')}/send-message"
            payload = {
                "phone": clean_phone,
                "message": text
            }

        async with httpx.AsyncClient(timeout=15.0) as client:
            res = await client.post(endpoint, json=payload, headers=headers)
            if res.status_code in [200, 201]:
                logger.info(f"WhatsApp message successfully sent to {clean_phone}")
                return True
            else:
                logger.warning(f"WhatsApp Gateway ({endpoint}) returned status {res.status_code}: {res.text}")
                return False
    except Exception as e:
        logger.error(f"Error sending WhatsApp message to {clean_phone}: {e}")
        return False

async def send_whatsapp_template(
    to_phone: str,
    template_name: str = "prospeccion_sofia_v1",
    language_code: str = "es_AR",
    components: Optional[List[dict]] = None
) -> bool:
    """
    Sends an approved Meta WhatsApp template to initiate outbound prospecting without ban risk.
    """
    clean_phone = "".join(filter(str.isdigit, to_phone))

    if settings.META_ACCESS_TOKEN and settings.META_PHONE_NUMBER_ID:
        meta_url = f"https://graph.facebook.com/v20.0/{settings.META_PHONE_NUMBER_ID}/messages"
        meta_headers = {
            "Authorization": f"Bearer {settings.META_ACCESS_TOKEN}",
            "Content-Type": "application/json"
        }
        for target_phone in get_phone_candidates(clean_phone):
            meta_payload = {
                "messaging_product": "whatsapp",
                "recipient_type": "individual",
                "to": target_phone,
                "type": "template",
                "template": {
                    "name": template_name,
                    "language": {
                        "code": language_code
                    }
                }
            }
            if components:
                meta_payload["template"]["components"] = components

            try:
                async with httpx.AsyncClient(timeout=15.0) as client:
                    res = await client.post(meta_url, json=meta_payload, headers=meta_headers)
                    if res.status_code in [200, 201]:
                        logger.info(f"✅ Meta WhatsApp Template '{template_name}' sent successfully to {target_phone}")
                        return True
                    else:
                        logger.warning(f"Meta Cloud API template returned status {res.status_code} for {target_phone}: {res.text}")
            except Exception as e:
                logger.error(f"Error sending Meta template to {target_phone}: {e}")

    logger.warning(f"Could not send template {template_name} to {clean_phone} via Meta Cloud API")
    return False


async def send_whatsapp_document(
    to_phone: str,
    document_url: str,
    filename: str = "Propuesta_Sofia_IA.pdf",
    caption: Optional[str] = None
) -> bool:
    """
    Sends a PDF or document through Meta WhatsApp Cloud API or Whapi.Cloud.
    """
    clean_phone = "".join(filter(str.isdigit, to_phone))

    # 1. Official Meta WhatsApp Cloud API (Primary Enterprise Gateway)
    if settings.META_ACCESS_TOKEN and settings.META_PHONE_NUMBER_ID:
        meta_url = f"https://graph.facebook.com/v20.0/{settings.META_PHONE_NUMBER_ID}/messages"
        meta_headers = {
            "Authorization": f"Bearer {settings.META_ACCESS_TOKEN}",
            "Content-Type": "application/json"
        }
        for target_phone in get_phone_candidates(clean_phone):
            meta_payload = {
                "messaging_product": "whatsapp",
                "recipient_type": "individual",
                "to": target_phone,
                "type": "document",
                "document": {
                    "link": document_url,
                    "filename": filename
                }
            }
            if caption:
                meta_payload["document"]["caption"] = caption

            try:
                async with httpx.AsyncClient(timeout=25.0) as client:
                    res = await client.post(meta_url, json=meta_payload, headers=meta_headers)
                    if res.status_code in [200, 201]:
                        logger.info(f"✅ Meta WhatsApp Cloud API document sent successfully to {target_phone}")
                        return True
                    else:
                        logger.warning(f"Meta Cloud API document returned status {res.status_code} for {target_phone}: {res.text}")
            except Exception as e:
                logger.error(f"Error sending document via Meta WhatsApp Cloud API for {target_phone}: {e}")

    # 2. Whapi.Cloud Fallback
    api_url = settings.WHATSAPP_API_URL
    api_token = settings.WHATSAPP_API_TOKEN

    if not api_url or not api_token:
        logger.info(f"[WHATSAPP SIMULATION] Document {filename} to {clean_phone} via {document_url}")
        return True

    try:
        headers = {
            "Authorization": f"Bearer {api_token}",
            "Content-Type": "application/json",
            "accept": "application/json"
        }

        endpoint = f"{api_url.rstrip('/')}/messages/document"
        payload = {
            "to": clean_phone,
            "media": document_url,
            "filename": filename
        }
        if caption:
            payload["caption"] = caption

        async with httpx.AsyncClient(timeout=25.0) as client:
            res = await client.post(endpoint, json=payload, headers=headers)
            if res.status_code in [200, 201]:
                logger.info(f"WhatsApp PDF document successfully sent to {clean_phone}")
                return True
            else:
                logger.warning(f"WhatsApp Document Gateway returned status {res.status_code}: {res.text}")
                return False
    except Exception as e:
        logger.error(f"Error sending WhatsApp document to {clean_phone}: {e}")
        return False

async def notify_javier_meeting_scheduled(
    prospect_name: str,
    contact_name: Optional[str],
    phone: str,
    city: Optional[str],
    meeting_details: str,
    last_message: str,
    campaign: str = "ai_agency"
) -> None:
    """
    Dual Alert System for Javier Coloma:
    1. WhatsApp immediate message to his private line (+54 9 343 453-6447).
    2. High-priority corporate HTML email to his inbox.
    """
    alert_phone = settings.WHATSAPP_ALERT_PHONE or "5493434536447"
    contact_str = contact_name or "Dueño / Administración"
    city_str = city or "Entre Ríos / Santa Fe"

    from app.services.calendar import generate_google_calendar_link
    cal_link = generate_google_calendar_link(
        summary=f"🎯 Demo Sofía IA: {prospect_name}",
        description=f"Reunión acordada por Sofía B2B SDR.\nContacto: {contact_str}\nTeléfono: +{phone}\nLocalidad: {city_str}\nHorario pactado: {meeting_details}\nÚltimo mensaje: {last_message}",
        location=f"{city_str} • Videollamada"
    )

    # 1. WhatsApp Alert
    if campaign == "ai_agency":
        wa_alert_text = (
            f"🔔 *¡NUEVA REUNIÓN CONFIRMADA! (Sofía AI Agency)*\n\n"
            f"🏢 *Empresa / Distribuidora:* {prospect_name}\n"
            f"👤 *Contacto:* {contact_str}\n"
            f"📱 *Teléfono:* +{phone}\n"
            f"📍 *Localidad:* {city_str}\n"
            f"⏰ *Horario pactado:* {meeting_details}\n"
            f"💬 *Último mensaje del cliente:* \"{last_message}\"\n\n"
            f"👉 *Acción:* Llamalo en ese horario para hacerle la demo de Sofía (Cupo especial: Setup $0 bonificado + $70.000-$100.000/mes de abono).\n\n"
            f"📅 *Agendar en 1 clic en Google Calendar:*\n{cal_link}"
        )
    else:
        wa_alert_text = (
            f"🔔 *¡NUEVA REUNIÓN CONFIRMADA! (Air Control)*\n\n"
            f"🏨 *Complejo:* {prospect_name}\n"
            f"👤 *Contacto:* {contact_str}\n"
            f"📱 *Teléfono:* +{phone}\n"
            f"📍 *Localidad:* {city_str}\n"
            f"⏰ *Horario pactado:* {meeting_details}\n"
            f"💬 *Último mensaje del cliente:* \"{last_message}\"\n\n"
            f"👉 *Acción:* Llamalo en ese horario para la reunión acordada.\n\n"
            f"📅 *Agendar en 1 clic en Google Calendar:*\n{cal_link}"
        )

    await send_whatsapp_message(to_phone=alert_phone, text=wa_alert_text)
    logger.info(f"WhatsApp appointment notification dispatched to Javier ({alert_phone}) for {prospect_name}")

    # 2. Corporate HTML Email Alert
    try:
        email_html = build_meeting_html_email(
            prospect_name=prospect_name,
            contact_name=contact_name,
            phone=phone,
            city=city,
            meeting_details=meeting_details,
            last_message=last_message,
            campaign=campaign
        )
        campaign_title = "Sofía AI Agency" if campaign == "ai_agency" else "Air Control"
        recipient_email = settings.MAIL_USERNAME or settings.MAIL_FROM or "colomajavier@gmail.com"

        await send_email_alert(
            subject=f"🎯 [{campaign_title}] Cita Confirmada: {prospect_name} ({meeting_details})",
            recipient=recipient_email,
            html_content=email_html
        )
    except Exception as email_err:
        logger.error(f"Error dispatching email alert: {email_err}")

async def notify_owner_order_confirmed(
    client_name: str,
    contact_name: Optional[str],
    phone: str,
    city: Optional[str],
    order_draft: Any,
    delivery_notes: Optional[str] = None
) -> None:
    """
    Dispatches instant notification to the business owner/depot about a confirmed customer order.
    """
    alert_phone = settings.WHATSAPP_ALERT_PHONE or "5493434536447"
    contact_str = contact_name or "Comercio"
    city_str = city or "No especificada"

    item_lines = []
    for it in order_draft.items:
        if it.in_stock:
            item_lines.append(f"• {it.quantity}x {it.product.name} ({it.product.presentation}): *{it.formatted_subtotal()}*")

    items_block = "\n".join(item_lines) if item_lines else "Sin items especificados"

    wa_text = (
        f"📦 *¡NUEVO PEDIDO CONFIRMADO!* 📦\n\n"
        f"👤 *Cliente:* {client_name}\n"
        f"📱 *Contacto:* {contact_str} (+{phone})\n"
        f"📍 *Zona/Localidad:* {city_str}\n\n"
        f"📝 *MERCADERÍA SOLICITADA:*\n"
        f"{items_block}\n\n"
        f"💰 *TOTAL ESTIMADO: {order_draft.formatted_total()}*\n"
        f"🚚 *Estado:* Ingresado para armado y reparto.\n\n"
        f"👉 *Contactar cliente:* https://wa.me/{phone}"
    )

    # Slight delay so confirmation reply arrives first in chat
    await asyncio.sleep(1.5)
    await send_whatsapp_message(to_phone=alert_phone, text=wa_text)
    logger.info(f"Order alert dispatched to owner ({alert_phone}) for {client_name}")

    try:
        from app.services.alerts import build_order_html_email
        email_html = build_order_html_email(
            client_name=client_name,
            contact_name=contact_name,
            phone=phone,
            city=city,
            order_items=order_draft.items,
            total_formatted=order_draft.formatted_total(),
            delivery_notes=delivery_notes
        )
        recipient_email = settings.MAIL_USERNAME or settings.MAIL_FROM or "colomajavier@gmail.com"
        await send_email_alert(
            subject=f"📦 [Nuevo Pedido] {client_name} - {order_draft.formatted_total()}",
            recipient=recipient_email,
            html_content=email_html
        )
    except Exception as e:
        logger.error(f"Error dispatching order email alert: {e}")

async def notify_owner_demo_requested(
    client_name: str,
    contact_name: Optional[str],
    phone: str,
    incoming_text: str
) -> None:
    """
    Dispatches instant notification to Javier when someone requests a demo or asks how the service works via WhatsApp.
    """
    alert_phone = settings.WHATSAPP_ALERT_PHONE or "5493434536447"
    contact_str = contact_name or "Contacto"

    wa_text = (
        f"🔔 *¡NUEVA SOLICITUD DE DEMO POR WHATSAPP!* 🎥\n\n"
        f"👤 *Contacto:* {contact_str}\n"
        f"📱 *Teléfono:* +{phone}\n"
        f"💬 *Mensaje:* «{incoming_text.strip()}»\n\n"
        f"👉 *Acción sugerida:* Enviarle el video demo de 86s o llamarlo:\n"
        f"https://wa.me/{phone}"
    )

    await asyncio.sleep(1.0)
    await send_whatsapp_message(to_phone=alert_phone, text=wa_text)
    logger.info(f"Demo request alert dispatched to owner ({alert_phone}) for {phone}")

async def send_whatsapp_audio(
    to_phone: str,
    audio_bytes: bytes,
    filename: str = "sofia_voice.mp3"
) -> bool:
    """
    Sends an audio message (voice note) through Meta WhatsApp Cloud API.
    """
    clean_phone = "".join(filter(str.isdigit, to_phone))

    if settings.META_ACCESS_TOKEN and settings.META_PHONE_NUMBER_ID:
        token = settings.META_ACCESS_TOKEN
        phone_id = settings.META_PHONE_NUMBER_ID
        upload_url = f"https://graph.facebook.com/v20.0/{phone_id}/media"
        headers = {"Authorization": f"Bearer {token}"}

        files = {
            "file": (filename, audio_bytes, "audio/mpeg")
        }
        data = {
            "messaging_product": "whatsapp",
            "type": "audio/mpeg"
        }

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                res = await client.post(upload_url, headers=headers, data=data, files=files)
                if res.status_code in [200, 201]:
                    media_id = res.json().get("id")
                    if media_id:
                        msg_url = f"https://graph.facebook.com/v20.0/{phone_id}/messages"
                        for target_phone in get_phone_candidates(clean_phone):
                            payload = {
                                "messaging_product": "whatsapp",
                                "recipient_type": "individual",
                                "to": target_phone,
                                "type": "audio",
                                "audio": {
                                    "id": media_id
                                }
                            }
                            send_res = await client.post(msg_url, headers=headers, json=payload)
                            if send_res.status_code in [200, 201]:
                                logger.info(f"✅ Meta WhatsApp audio sent successfully to {target_phone}")
                                return True
                            else:
                                logger.warning(f"Meta send audio failed for {target_phone}: {send_res.text}")
                else:
                    logger.warning(f"Meta audio upload failed: {res.status_code} {res.text}")
        except Exception as e:
            logger.error(f"Error sending WhatsApp audio to {clean_phone}: {e}")

    return False

