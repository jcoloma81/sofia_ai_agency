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

def split_whatsapp_message(text: str, max_chars: int = 3800) -> List[str]:
    """
    Splits long messages so they do not exceed Meta WhatsApp Cloud API limit (4096 chars).
    Splits cleanly on paragraph breaks ('\n\n'), line breaks ('\n'), or spaces.
    """
    if not text or len(text) <= max_chars:
        return [text] if text else []

    chunks = []
    paragraphs = text.split("\n\n")
    current_chunk = ""

    for p in paragraphs:
        if not p.strip():
            continue
        if current_chunk and (len(current_chunk) + len(p) + 2 > max_chars):
            chunks.append(current_chunk.strip())
            current_chunk = p
        elif len(p) > max_chars:
            lines = p.split("\n")
            for line in lines:
                if current_chunk and (len(current_chunk) + len(line) + 1 > max_chars):
                    chunks.append(current_chunk.strip())
                    current_chunk = line
                elif len(line) > max_chars:
                    words = line.split(" ")
                    for word in words:
                        if current_chunk and (len(current_chunk) + len(word) + 1 > max_chars):
                            chunks.append(current_chunk.strip())
                            current_chunk = word
                        else:
                            current_chunk = f"{current_chunk} {word}" if current_chunk else word
                else:
                    current_chunk = f"{current_chunk}\n{line}" if current_chunk else line
        else:
            current_chunk = f"{current_chunk}\n\n{p}" if current_chunk else p

    if current_chunk.strip():
        chunks.append(current_chunk.strip())

    return chunks

async def _send_single_whatsapp_message(clean_phone: str, text: str) -> bool:
    """
    Sends a single chunk via Official Meta WhatsApp Cloud API (Primary Enterprise Gateway),
    or falls back to Whapi.Cloud, or simulation log.
    """
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

async def send_whatsapp_message(to_phone: str, text: str) -> bool:
    """
    Sends a WhatsApp message via Official Meta WhatsApp Cloud API (Primary Enterprise Gateway),
    or falls back to Whapi.Cloud, or simulation log.
    Automatically splits long messages (>3800 chars) to adhere to Meta Cloud API limits.
    """
    clean_phone = "".join(filter(str.isdigit, to_phone))
    if not clean_phone or not text:
        return False

    chunks = split_whatsapp_message(text, max_chars=3800)
    all_success = True

    for i, chunk in enumerate(chunks):
        if i > 0:
            await asyncio.sleep(0.4)

        chunk_sent = await _send_single_whatsapp_message(clean_phone, chunk)
        if not chunk_sent:
            all_success = False

    return all_success

async def send_whatsapp_template(
    to_phone: str,
    template_name: str = "prospeccion_sofia_v1",
    language_code: str = "es_AR",
    components: Optional[List[dict]] = None,
    tenant_id: Optional[int] = None,
    db: Optional[Any] = None,
    body_params: Optional[List[str]] = None
) -> bool:
    """
    Sends an approved Meta WhatsApp template to initiate outbound messaging without ban risk.
    Enforces tenant message quota on the Shared Plan.
    If body_params is provided, automatically packages them into standard Meta Cloud API body components.
    """
    clean_phone = "".join(filter(str.isdigit, to_phone))
    if not clean_phone:
        return False

    if body_params and not components:
        components = [
            {
                "type": "body",
                "parameters": [{"type": "text", "text": str(p)} for p in body_params]
            }
        ]

    tenant = None
    if tenant_id and db:
        try:
            from app.models.tenant import Tenant
            from app.services.mercado_pago_service import mercadopago_service
            tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
            if tenant:
                can_send, remaining, reason = mercadopago_service.check_outbound_quota(tenant)
                if not can_send:
                    logger.warning(f"🚫 Quota exhausted ({remaining} remaining) for tenant {tenant.slug}. Triggering alert with MP link.")
                    await mercadopago_service.handle_quota_exhausted_alert(db, tenant)
                    return False
        except Exception as e:
            logger.error(f"Error checking tenant quota in send_whatsapp_template: {e}")

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
                        if tenant and db:
                            try:
                                tenant.messages_sent_this_month = (tenant.messages_sent_this_month or 0) + 1
                                db.commit()
                            except Exception:
                                pass
                        return True
                    else:
                        logger.warning(f"Meta Cloud API template returned status {res.status_code} for {target_phone}: {res.text}")
            except Exception as e:
                logger.error(f"Error sending Meta template to {target_phone}: {e}")

        logger.warning(f"Could not send template {template_name} to {clean_phone} via Meta Cloud API")
        return False

    # Simulation fallback if Meta credentials are not configured
    logger.info(f"[WHATSAPP SIMULATION] Meta Template '{template_name}' to {clean_phone} (Params: {body_params or components})")
    if tenant and db:
        try:
            tenant.messages_sent_this_month = (tenant.messages_sent_this_month or 0) + 1
            db.commit()
        except Exception:
            pass
    return True


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


async def send_whatsapp_video(
    to_phone: str,
    video_url: str,
    caption: Optional[str] = None
) -> bool:
    """
    Sends a video through Meta WhatsApp Cloud API.
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
                "type": "video",
                "video": {
                    "link": video_url
                }
            }
            if caption:
                meta_payload["video"]["caption"] = caption

            try:
                async with httpx.AsyncClient(timeout=30.0) as client:
                    res = await client.post(meta_url, json=meta_payload, headers=meta_headers)
                    if res.status_code in [200, 201]:
                        logger.info(f"✅ Meta WhatsApp Cloud API video sent successfully to {target_phone}")
                        return True
                    else:
                        logger.warning(f"Meta Cloud API video returned status {res.status_code} for {target_phone}: {res.text}")
            except Exception as e:
                logger.error(f"Error sending video via Meta WhatsApp Cloud API for {target_phone}: {e}")

    return False


async def send_whatsapp_image(
    to_phone: str,
    image_url: str,
    caption: Optional[str] = None
) -> bool:
    """
    Sends an HD image / logo banner through Meta WhatsApp Cloud API.
    Used for tenant branding banners (Clínica, Gym, Óptica) and property / product photos.
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
                "type": "image",
                "image": {
                    "link": image_url
                }
            }
            if caption:
                meta_payload["image"]["caption"] = caption

            try:
                async with httpx.AsyncClient(timeout=25.0) as client:
                    res = await client.post(meta_url, json=meta_payload, headers=meta_headers)
                    if res.status_code in [200, 201]:
                        logger.info(f"✅ Meta WhatsApp Cloud API image sent successfully to {target_phone}")
                        return True
                    else:
                        logger.warning(f"Meta Cloud API image returned status {res.status_code} for {target_phone}: {res.text}")
            except Exception as e:
                logger.error(f"Error sending image via Meta WhatsApp Cloud API for {target_phone}: {e}")

    # Fallback to simulation log
    logger.info(f"[WHATSAPP SIMULATION] Image to {clean_phone}: {image_url} (Caption: {caption})")
    return True


async def send_whatsapp_interactive_buttons(
    to_phone: str,
    body_text: str,
    buttons: List[dict],
    header_text: Optional[str] = None,
    footer_text: Optional[str] = None
) -> bool:
    """
    Sends interactive quick-reply buttons via Meta WhatsApp Cloud API.
    Example buttons: [{"id": "btn_confirmar", "title": "✅ SÍ, CONFIRMO"}, {"id": "btn_cancelar", "title": "❌ REPROGRAMAR"}]
    """
    clean_phone = "".join(filter(str.isdigit, to_phone))

    if settings.META_ACCESS_TOKEN and settings.META_PHONE_NUMBER_ID:
        meta_url = f"https://graph.facebook.com/v20.0/{settings.META_PHONE_NUMBER_ID}/messages"
        meta_headers = {
            "Authorization": f"Bearer {settings.META_ACCESS_TOKEN}",
            "Content-Type": "application/json"
        }
        interactive_obj = {
            "type": "button",
            "body": {"text": body_text},
            "action": {
                "buttons": [
                    {
                        "type": "reply",
                        "reply": {
                            "id": btn["id"],
                            "title": btn["title"][:20]  # Meta limit: max 20 chars
                        }
                    }
                    for btn in buttons[:3]  # Meta limit: max 3 quick-reply buttons
                ]
            }
        }
        if header_text:
            interactive_obj["header"] = {"type": "text", "text": header_text[:60]}
        if footer_text:
            interactive_obj["footer"] = {"text": footer_text[:60]}

        for target_phone in get_phone_candidates(clean_phone):
            meta_payload = {
                "messaging_product": "whatsapp",
                "recipient_type": "individual",
                "to": target_phone,
                "type": "interactive",
                "interactive": interactive_obj
            }
            try:
                async with httpx.AsyncClient(timeout=15.0) as client:
                    res = await client.post(meta_url, json=meta_payload, headers=meta_headers)
                    if res.status_code in [200, 201]:
                        logger.info(f"✅ Meta WhatsApp interactive buttons sent successfully to {target_phone}")
                        return True
                    else:
                        logger.warning(f"Meta Cloud API interactive returned status {res.status_code} for {target_phone}: {res.text}")
            except Exception as e:
                logger.error(f"Error sending interactive buttons via Meta WhatsApp Cloud API for {target_phone}: {e}")

    # Fallback to plain text with button titles listed
    fallback_text = body_text
    if buttons:
        btn_lines = "\n".join([f"• {b['title']}" for b in buttons])
        fallback_text += f"\n\n*Opciones:*\n{btn_lines}"
    return await _send_single_whatsapp_message(clean_phone, fallback_text)


async def send_owner_or_admin_alert(
    to_phone: str,
    fallback_text: str,
    business_name: str = "Sofía AI Agency",
    event_type: str = "Aviso del Sistema",
    client_title: str = "Cliente",
    details_summary: str = "",
    template_candidates: Optional[List[str]] = None,
    owner_email: Optional[str] = None
) -> bool:
    """
    Bulletproof Multi-Channel (WhatsApp + Email) Owner/Admin Notification Gateway:
    1. First attempts to deliver via an Official Meta Pre-Approved Template
       (bypassing Meta's 24-hour customer window and guaranteeing delivery 24/7/365).
    2. If template delivery is not available (e.g. pending approval or error),
       falls back to standard WhatsApp message delivery.
    3. If owner_email is provided, also dispatches a high-priority HTML email
       for immediate backup and zero-loss notification redundancy.
    """
    clean_phone = "".join(filter(str.isdigit, to_phone))
    if not clean_phone:
        return False

    # Multi-channel backup: Dispatch HTML email alert if owner_email is configured
    if owner_email and "@" in owner_email:
        try:
            from app.services.alerts import send_email_alert, build_operational_event_html_email
            email_html = build_operational_event_html_email(
                business_name=business_name,
                event_title=event_type,
                details_summary=details_summary or fallback_text,
                action_needed=client_title,
                recipient_name=business_name
            )
            asyncio.create_task(send_email_alert(
                subject=f"🔔 [{business_name}] {event_type}",
                recipient=owner_email.strip(),
                html_content=email_html
            ))
            logger.info(f"📧 Dual-channel email alert queued for {owner_email} ({business_name})")
        except Exception as email_err:
            logger.debug(f"Dual email dispatch to {owner_email} failed: {email_err}")

    candidates = template_candidates or ["notificacion_operativa_v1", "alerta_nueva_cita_v1", "alerta_nueva_cita_v2"]

    for tmpl in candidates:
        try:
            body_params = [
                str(business_name)[:60],
                str(event_type)[:60],
                str(client_title)[:80],
                str(details_summary)[:200]
            ]
            sent = await send_whatsapp_template(
                to_phone=clean_phone,
                template_name=tmpl,
                language_code="es_AR",
                body_params=body_params
            )
            if sent:
                logger.info(f"✅ Owner/Admin alert delivered via Meta Template '{tmpl}' to {clean_phone}")
                return True
        except Exception as e:
            logger.debug(f"Template '{tmpl}' attempt failed for {clean_phone}: {e}")

    # Fallback to direct message
    logger.info(f"Dispatching owner alert to {clean_phone} via standard message channel")
    return await send_whatsapp_message(to_phone=clean_phone, text=fallback_text)


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
    1. WhatsApp immediate message to his private line (+54 9 343 453-6447) via Template or direct message.
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
            f"👉 *Acción:* Contactalo para coordinar la demo de Sofía (Abono accesible: $30.000/mes).\n\n"
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

    await send_owner_or_admin_alert(
        to_phone=alert_phone,
        fallback_text=wa_alert_text,
        business_name="Sofía AI Agency" if campaign == "ai_agency" else "Air Control",
        event_type="Reunión Confirmada",
        client_title=f"{prospect_name} ({contact_str}) - +{phone}",
        details_summary=f"Horario: {meeting_details}. {city_str}. Último mensaje: {last_message}"
    )
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
    await send_owner_or_admin_alert(
        to_phone=alert_phone,
        fallback_text=wa_text,
        business_name="Sofía AI Agency",
        event_type="Nuevo Pedido",
        client_title=f"{client_name} (+{phone})",
        details_summary=f"Total: {order_draft.formatted_total()}. {city_str}."
    )
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
    await send_owner_or_admin_alert(
        to_phone=alert_phone,
        fallback_text=wa_text,
        business_name="Sofía AI Agency",
        event_type="Solicitud de Demo",
        client_title=f"{contact_str} (+{phone})",
        details_summary=incoming_text.strip()
    )
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

        # Detect if audio is OGG Opus (starts with OggS magic bytes)
        is_ogg = audio_bytes[:4] == b"OggS"
        mime_type = "audio/ogg" if is_ogg else "audio/mpeg"
        upload_name = "voice_note.ogg" if is_ogg else filename

        files = {
            "file": (upload_name, audio_bytes, mime_type)
        }
        data = {
            "messaging_product": "whatsapp",
            "type": mime_type
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

