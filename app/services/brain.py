import re
import json
import logging
from typing import Dict, Any, Tuple, Optional, List
import httpx
from app.config.settings import settings

logger = logging.getLogger(__name__)

SYSTEM_PROMPT_AGENCY = """Sos Sofía, ejecutiva comercial y asistente comercial de soluciones de Inteligencia Artificial para empresas, comercios y distribuidoras.
Tu único rol es conversar por WhatsApp con dueños, gerentes comerciales y administradores de empresas o distribuidoras de forma natural, cálida, profesional y empática (voseo argentino, sin formalismos robots).

REGLAS DE IDENTIDAD Y ESTILO:
- Te llamás Sofía. Sos un agente comercial con Inteligencia Artificial que trabaja en WhatsApp.
- Cero repetición de saludos: NO vuelvas a decir "¡Hola!" o "¿Cómo estás?" si la conversación ya está iniciada. Respondé directo al grano.
- Cero tecnicismos ni formalismos acartonados: PROHIBIDO decir "Estimado/a", "Nos dirigimos a usted", "Quedo a su entera disposición".
- Tampoco uses lunfardo vulgar ni groserías. Mantené un tono profesional, educado y cercano.

PROPUESTA DE VALOR (SI PREGUNTAN CÓMO FUNCIONA O QUÉ HACE EL SISTEMA):
- Diferencia fundamental: NO sos un bot pasivo de respuestas automáticas de WhatsApp Business. Funcionás como una ejecutiva comercial digital activa: buscás comercios y clientes potenciales en Google Maps y les escribís de forma autónoma a entre 12 y 15 empresas de su interés por día, con el logo de su negocio, para contactar nuevos clientes.
- Responde dudas, envía catálogo o lista de precios en PDF al instante (24/7) y hasta escucha y procesa notas de voz de los clientes.
- Apenas detecta un cliente interesado o con intención de reunión/pedido, envía una alerta automática e instantánea al celular personal del dueño o vendedor con los datos y la cita lista para facturar.
- Si el mensaje entrante es una respuesta automática de bienvenida o ausencia de WhatsApp Business (ej: "Gracias por comunicarte...", "Nuestro horario es..."), no te desorientes: respondé con cordialidad y preguntale al titular o encargado con quién tenés el gusto y qué día le quedaría cómodo conversar 10 minutos.

MANEJO DE TONO Y CUÁNDO USAR "¡PERFECTO!":
1. Preguntas o dudas secas del cliente (ej: "¿Cómo funciona?", "¿Cuánto sale?", "¿De qué se trata?"):
   - PROHIBIDO decir "¡Perfecto!" (suena desubicado y robótico).
   - Respondé de forma sobria, natural y directa:
     "Para mostrarte en detalle el funcionamiento según el rubro de tu empresa, ver una demo en vivo y los costos adaptados, nuestro asesor se pone en contacto con ustedes en una charla breve de 10 minutos (presencial si están en la zona o por videollamada corta)."
   - Y sumás la pregunta para coordinar:
     - Si no sabés su nombre: "¿Con quién tengo el gusto y qué día y horario te quedaría cómodo?"
     - Si ya sabés su nombre: "¿Qué día y horario te quedaría cómodo, [Nombre]?"

2. Aceptación o propuesta de día/horario (ej: "Dale", "El martes a las 10", "Mañana a la tarde", "Llamame el lunes"):
   - ACÁ SÍ usás "¡Perfecto!":
     "¡Perfecto [Nombre]! Ya te dejo agendada la reunión para [día y hora pactados]. Nuestro asesor se va a comunicar puntual con vos por este mismo medio. ¡Muchas gracias y que tengas un gran día!"
   - NO sigas dando vueltas ni extendiendo el diálogo una vez pactada la reunión. Dejalo asentado y listo.

REGLA DE ORO:
- Vos sos una Appointment Setter (agendadora de reuniones comerciales). NO vendés ni cerrás contratos técnicos por chat (de eso se encarga nuestro asesor en la charla de 10 minutos).
- NO pidas el número de teléfono (ya estamos conversando directamente por su WhatsApp).
"""

SYSTEM_PROMPT_AIR_CONTROL = """Sos Sofía, asistente comercial de Air Control en Entre Ríos, Argentina.
Tu único rol es conversar por WhatsApp con dueños y administradores de hoteles, cabañas y alojamientos turísticos de forma natural, cálida, profesional y empática (voseo argentino, sin formalismos robots).

REGLAS DE IDENTIDAD Y ESTILO:
- La empresa se llama "Air Control" (NUNCA digas "Air Control PRO" en la conversación).
- Cero repetición de saludos: NO vuelvas a decir "¡Hola!" o "¿Cómo estás?" si la conversación ya está iniciada. Respondé directo al grano.
- Cero tecnicismos ni formalismos acartonados: PROHIBIDO decir "Estimado/a", "Nos dirigimos a usted", "Quedo a su entera disposición".
- Tampoco uses lunfardo vulgar ni groserías. Mantené un tono profesional, educado y cercano.

MANEJO DE TONO Y CUÁNDO USAR "¡PERFECTO!":
1. Preguntas o dudas secas del cliente (ej: "¿Cómo funciona?", "¿Cuánto sale?", "¿De qué se trata?"):
   - PROHIBIDO decir "¡Perfecto!" (suena desubicado y robótico).
   - Respondé de forma sobria, natural y directa:
     "Para explicarte en detalle sobre los precios y el funcionamiento según la cantidad de habitaciones de tu complejo, nuestro asesor se pone en contacto con ustedes en una charla breve de 10 minutos (presencial si están en Paraná o por videollamada corta)."
   - Y sumás la pregunta para coordinar:
     - Si no sabés su nombre: "¿Con quién tengo el gusto y qué día y horario te quedaría cómodo?"
     - Si ya sabés su nombre: "¿Qué día y horario te quedaría cómodo, [Nombre]?"

2. Aceptación o propuesta de día/horario (ej: "Dale", "El martes a las 10", "Mañana a la tarde"):
   - ACÁ SÍ usás "¡Perfecto!":
     "¡Perfecto [Nombre]! Ya te dejo agendada la reunión para [día y hora pactados]. Nuestro asesor se va a comunicar puntual con vos por este mismo medio. ¡Muchas gracias y que tengas un gran día!"
   - NO sigas dando vueltas ni extendiendo el diálogo una vez pactada la reunión. Dejalo asentado y listo.

REGLA DE ORO:
- Vos NO vendés ni explicás el funcionamiento técnico del sistema (de eso se encarga nuestro asesor en persona o videollamada).
- NO pidas el número de teléfono (ya estamos conversando directamente por su WhatsApp).
"""

def detect_meeting_intent(text: str) -> Tuple[bool, Optional[str]]:
    """
    Analyzes prospect's message to detect if they are proposing or agreeing to a meeting date/time.
    Returns (is_meeting_confirmed, meeting_details_str)
    """
    if not text:
        return False, None

    text_lower = text.lower()
    
    has_agreement = bool(re.search(r'\b(dale|bueno|perfecto|ok|s[ií]|coordinemos|llamame|que me llame|charlemos|dale dale|agendalo|agendá|puede ser|podria ser|podría ser|me parece bien|me queda bien|me viene bien|de acuerdo|listo)\b', text_lower))
    has_day = bool(re.search(r'\b(hoy|mañana|lunes|martes|mi[eé]rcoles|jueves|viernes|s[aá]bado|domingo|semana que viene|esta semana)\b', text_lower))
    has_hour = bool(re.search(r'(\d{1,2}\s*(?::|\.)\s*\d{2}|\d{1,2}\s*hs|\d{1,2}\s*horas?|a las \d{1,2}|como a las \d{1,2}|tipo \d{1,2}|alrededor de las \d{1,2}|a eso de las \d{1,2}|de la tarde|de la mañana|a la tarde|a la mañana|al mediod[ií]a|por la tarde|por la mañana)', text_lower))
    
    if (has_day and has_hour) or (has_agreement and (has_day or has_hour)) or ("llamame" in text_lower) or ("que me llame" in text_lower):
        clean_detail = text.strip()
        return True, clean_detail

    # Direct short response proposing or confirming day/hour (e.g. "Mañana", "El martes", "A las 11 hs")
    if (has_day or has_hour) and len(text_lower.split()) <= 6 and not any(q in text_lower for q in ["cuanto", "cuánto", "precio", "que es", "qué es", "como es", "cómo es"]):
        clean_detail = text.strip()
        return True, clean_detail
        
    return False, None

def detect_catalog_request(text: str) -> bool:
    """
    Detects if the prospect is asking for a PDF proposal, catalog, price list, or brochures.
    """
    if not text:
        return False
    text_lower = text.lower()
    return bool(re.search(
        r'\b(pdf|folleto|propuesta|cat[aá]logo|lista de precios|tarifario|presentaci[oó]n|mandame algo|pasame algo|enviame algo|mandame info|pasame info|mas info|más info|informaci[oó]n por escrito)\b',
        text_lower
    ))

def rule_based_consultative_response(
    incoming_text: str,
    prospect_name: Optional[str] = None,
    contact_name: Optional[str] = None,
    campaign: str = "ai_agency"
) -> Tuple[str, bool, Optional[str]]:
    """
    Reliable Argentine consultative fallback response engine in case external LLM API is unreachable.
    Returns (response_text, is_meeting_confirmed, meeting_details)
    """
    text_lower = incoming_text.lower()
    
    # Check meeting intent first
    is_meeting, meeting_details = detect_meeting_intent(incoming_text)
    if is_meeting:
        nombre = f" {contact_name}" if contact_name else ""
        return (
            f"¡Perfecto{nombre}! Ya te dejo agendada la reunión para {meeting_details}. "
            f"Nuestro asesor se va a comunicar puntual con vos por este mismo medio. "
            f"¡Muchas gracias y que tengas un gran día!",
            True,
            meeting_details
        )

    # PDF / Catalog request rule
    if detect_catalog_request(incoming_text):
        nombre = f" {contact_name}" if contact_name else ""
        cierre = f"¿Qué día y horario te quedaría cómodo charlar 10 minutos con Lucas, nuestro asesor?" if not contact_name else f"¿Qué día y horario te quedaría cómodo charlar 10 minutos con Lucas, {contact_name}?"
        return (
            f"¡Por supuesto{nombre}! Ahí te acabo de adjuntar nuestra propuesta completa en PDF con el funcionamiento, casos de uso y costos detallados.\n\n"
            f"{cierre}",
            False,
            None
        )

    # Voice note fallback if speech-to-text / Gemini failed
    if "(nota de voz" in text_lower or "(audio" in text_lower:
        nombre = f" {contact_name}" if contact_name else ""
        return (
            f"¡Hola{nombre}! Justo estoy en la computadora y no pude escuchar con claridad el audio. ¿Me podrás escribir en un mensajito breve o confirmarme qué día y horario te queda cómodo conversar 10 minutos con Lucas, nuestro asesor?",
            False,
            None
        )

    # Rejection / No interest
    if any(k in text_lower for k in ["no me interesa", "no gracias", "por ahora no", "no por ahora", "no estamos interesados"]):
        return (
            "¡Entendido totalmente! Te agradezco mucho por responder y cualquier cosa tenés nuestro contacto por acá. ¡Que tengas una excelente jornada!",
            False,
            None
        )

    # Simple presence check / Greeting only (e.g. "Hola Sofía estás?", "Hola", "Buenas", "¿Estás ahí?")
    clean_words = re.findall(r'\b\w+\b', text_lower)
    is_greeting = any(w in ["hola", "buenas", "buen", "dia", "dias", "tardes", "que", "tal"] for w in clean_words)
    is_presence = any(w in ["estas", "estás", "ahi", "ahí", "alguien"] for w in clean_words)
    has_specific_question = any(k in text_lower for k in [
        "precio", "costo", "sale", "abono", "romper", "obra", "instala",
        "trata", "funciona", "que es", "qué es", "como es", "cómo es",
        "cuanto", "cuánto", "donde", "dónde", "demo"
    ])

    if (is_presence or is_greeting) and not has_specific_question and len(clean_words) <= 6:
        nombre = f" {contact_name}" if contact_name else ""
        return (
            f"¡Hola{nombre}! Sí, acá estoy. Decime, ¿en qué te puedo dar una mano?",
            False,
            None
        )

    # Gratitude only ("gracias", "muchas gracias")
    if any(k in text_lower for k in ["gracias", "muchas gracias"]) and not has_specific_question:
        return (
            "¡De nada! Cualquier duda o consulta que te surja, avisame por acá. ¡Un saludo!",
            False,
            None
        )

    # Bridge all inquiries soberly to meeting setting without fake cheerfulness
    pregunta_cierre = f"¿Qué día y horario te quedaría más cómodo, {contact_name}?" if contact_name else "¿Con quién tengo el gusto y qué día y horario te quedaría más cómodo?"
    if campaign == "ai_agency":
        return (
            f"Para mostrarte en detalle el funcionamiento según el rubro de tu empresa, ver una demo en vivo y los costos adaptados, nuestro asesor se pone en contacto con ustedes en una charla breve de 10 minutos (presencial si están en la zona o por videollamada corta).\n\n"
            f"{pregunta_cierre}",
            False,
            None
        )

    return (
        f"Para explicarte en detalle sobre los precios y el funcionamiento según las características de tu complejo, nuestro asesor se pone en contacto con ustedes en una charla breve de 10 minutos (presencial si están en Paraná o por videollamada corta).\n\n"
        f"{pregunta_cierre}",
        False,
        None
    )

async def transcribe_audio_gemini(audio_b64: str, audio_mime_type: Optional[str] = None) -> Optional[str]:
    """
    Transcribes voice note audio into text using Gemini Speech/Audio Multimodal.
    Supports dedicated Google transcription models (gemini-3.5-transcribe) and fallback models.
    """
    gemini_key = settings.GEMINI_API_KEY
    if not gemini_key or not audio_b64:
        return None

    clean_mime = audio_mime_type.split(";")[0].strip() if audio_mime_type else "audio/ogg"
    payload = {
        "contents": [
            {
                "parts": [
                    {"inline_data": {"mime_type": clean_mime, "data": audio_b64}},
                    {"text": "Transcribí de forma exacta las palabras dichas en esta nota de voz en español. Respondé únicamente con la transcripción exacta sin comentarios."}
                ]
            }
        ]
    }

    candidate_models = [
        "gemini-3.5-transcribe",
        "gemini-flash-lite-latest",
        "gemini-3.5-flash-lite",
        "gemini-3.6-flash"
    ]
    for model_name in candidate_models:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={gemini_key}"
        try:
            async with httpx.AsyncClient(timeout=25.0) as client:
                res = await client.post(url, json=payload)
                if res.status_code == 200:
                    data = res.json()
                    candidates = data.get("candidates", [])
                    if candidates and "content" in candidates[0]:
                        parts = candidates[0]["content"].get("parts", [])
                        for part in parts:
                            text_val = (
                                part.get("audioTranscription", {}).get("text")
                                or part.get("text", "")
                            )
                            if text_val and text_val.strip():
                                logger.info(f"🎙️ Audio transcribed successfully via {model_name}: '{text_val.strip()}'")
                                return text_val.strip()
                else:
                    logger.warning(f"Audio transcription {model_name} returned status {res.status_code}: {res.text[:120]}")
        except Exception as e:
            logger.warning(f"Error transcribing audio with {model_name}: {e}")

    return None

async def generate_ai_response(
    incoming_text: str,
    conversation_history: list,
    prospect_name: Optional[str] = None,
    contact_name: Optional[str] = None,
    city: Optional[str] = None,
    audio_data_b64: Optional[str] = None,
    audio_mime_type: Optional[str] = None,
    campaign: str = "ai_agency"
) -> Tuple[str, bool, Optional[str]]:
    """
    Generates response using Gemini Flash Lite Multimodal API (with text and audio note support) if key is available,
    or falls back cleanly to the rule-based Argentine conversational engine.
    Returns (response_text, is_meeting_confirmed, meeting_details)
    """
    is_meeting, meeting_details = detect_meeting_intent(incoming_text)
    
    gemini_key = settings.GEMINI_API_KEY
    if not gemini_key:
        logger.info("GEMINI_API_KEY not configured. Using rule-based consultative engine.")
        return rule_based_consultative_response(incoming_text, prospect_name, contact_name, campaign=campaign)

    try:
        contents = []
        selected_prompt = SYSTEM_PROMPT_AGENCY if campaign == "ai_agency" else SYSTEM_PROMPT_AIR_CONTROL
        entity_label = "Empresa / Distribuidora" if campaign == "ai_agency" else "Complejo"
        
        from app.services.directives import directives_service
        from app.services.catalog import catalog_service
        directives_ctx = directives_service.get_prompt_context() if campaign == "ai_agency" else ""
        catalog_ctx = catalog_service.get_summary_prompt() if (campaign == "ai_agency" and catalog_service.products) else ""

        system_context = (
            f"{selected_prompt}\n\n"
            f"Datos actuales:\n"
            f"- {entity_label}: {prospect_name or 'No especificado'}\n"
            f"- Contacto: {contact_name or 'Estimado'}\n"
            f"- Localidad: {city or 'Entre Ríos / Santa Fe'}\n\n"
            f"{directives_ctx}\n\n"
            f"{catalog_ctx}\n"
        )

        for msg in conversation_history[-6:]:
            role = "user" if msg.get("sender") == "prospect" else "model"
            contents.append({
                "role": role,
                "parts": [{"text": msg.get("text", "")}]
            })

        if audio_data_b64:
            clean_mime = audio_mime_type.split(";")[0].strip() if audio_mime_type else "audio/ogg"
            current_parts = [
                {"inline_data": {"mime_type": clean_mime, "data": audio_data_b64}},
                {"text": "El cliente envió esta nota de voz por WhatsApp. Escuchala con atención y respondé en texto con calidez, voseo argentino y siguiendo estrictamente tus directivas de Sofía."}
            ]
        else:
            current_parts = [{"text": incoming_text}]

        contents.append({
            "role": "user",
            "parts": current_parts
        })

        payload = {
            "systemInstruction": {
                "parts": [{"text": system_context}]
            },
            "contents": contents,
            "generationConfig": {
                "temperature": 0.2,
                "maxOutputTokens": 300
            }
        }

        candidate_models = [
            "gemini-flash-lite-latest",
            "gemini-3.5-flash-lite",
            "gemini-3.6-flash"
        ]
        for model_name in candidate_models:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={gemini_key}"
            try:
                async with httpx.AsyncClient(timeout=4.0) as client:
                    res = await client.post(url, json=payload)
                    if res.status_code == 200:
                        data = res.json()
                        candidates = data.get("candidates", [])
                        if candidates and "content" in candidates[0]:
                            ai_text = candidates[0]["content"]["parts"][0]["text"].strip()
                            if not is_meeting:
                                if any(k in ai_text.lower() for k in ["agendada la reunión", "te dejo agendad", "agendada para", "reunión agendada", "agendado"]):
                                    is_meeting = True
                                    match = re.search(r'(?:agendada la reunión para|reunión para|agendada para|te dejo agendad[ao] para)\s+([^.!\n]+)', ai_text, re.IGNORECASE)
                                    if match:
                                        meeting_details = match.group(1).strip()
                                    else:
                                        meeting_details = "Acordado por nota de voz" if audio_data_b64 else incoming_text
                            return ai_text, is_meeting, meeting_details
                    else:
                        logger.warning(f"Model {model_name} returned status {res.status_code}. Trying next candidate.")
            except Exception as model_err:
                logger.warning(f"Error calling {model_name}: {model_err}")

        logger.warning("All Gemini candidate models failed or timed out. Falling back to rule engine.")
        return rule_based_consultative_response(incoming_text, prospect_name, contact_name, campaign=campaign)

    except Exception as e:
        logger.error(f"Error in Gemini generation: {e}. Falling back.")
        return rule_based_consultative_response(incoming_text, prospect_name, contact_name, campaign=campaign)
