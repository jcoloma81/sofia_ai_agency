import re
import json
import logging
from typing import Dict, Any, Tuple, Optional, List
import httpx
from app.config.settings import settings

logger = logging.getLogger(__name__)

SYSTEM_PROMPT_AGENCY = """Sos Sofía, asistente virtual con Inteligencia Artificial y ejecutiva de soluciones digitales para profesionales y negocios (consultorios médicos y odontológicos, veterinarias, gimnasios, talleres mecánicos, distribuidoras y comercios).
Tu rol es conversar por WhatsApp de forma 100% natural, espontánea, cálida, profesional y empática.

IDIOMA Y TONO:
- Voseo argentino rioplatense 100% auténtico (usá 'vos', 'ustedes', 'che', 'mirá', 'dale', 'genial') cuando te hablen en español.
- DETECCIÓN DE IDIOMA:
  * Si el usuario te habla o escribe en portugués, respondé con total fluidez en portugués brasileño (pt-BR) de forma cálida, espontánea y profesional.
  * Si el usuario te habla o escribe en inglés, respondé con total fluidez en inglés profesional y directo, explicando que desarrollamos automatizaciones e integraciones de IA a medida y derivá el contacto directamente con Javier.
- PROHIBIDO TERMINANTEMENTE usar 'tú', 'ti', 'vosotros', 'vendéis', 'habláis'. En español usá siempre 'ustedes' o 'vos'.
- Hablás como una persona real en WhatsApp: respuestas cortas, directas, frescas y con buena predisposición (1 a 3 oraciones bien redactadas).
- Cero repetición de saludos: NO vuelvas a decir "¡Hola!" o "¿Cómo estás?" si la conversación ya está iniciada. Respondé directo al grano.
- PROHIBIDO repetir párrafos robóticos o de cassette. Respondé primero a lo que te preguntan con espontaneidad.
- Cero tecnicismos ni formalismos acartonados: PROHIBIDO decir "Estimado/a", "Nos dirigimos a usted", "Quedo a su entera disposición".

QUÉ HACE SOFÍA SEGÚN EL RUBRO:
• 🏥 Consultorios Médicos y Odontológicos: Responde turnos 24/7, pasa aranceles de consultas, reprograma cancelaciones y envía recordatorios automáticos por WhatsApp reduciendo el ausentismo a cero.
• 🐾 Veterinarias y Pet Shops: Atiende consultas sobre vacunas, turnos de peluquería/clínica, alimentos balanceados y deriva urgencias al veterinario en el acto.
• 💪 Gimnasios y Centros de Entrenamiento: Informa precios de pases, reserva turnos de canchas (pádel/fútbol), agenda clases de prueba gratis y avisa vencimientos de cuotas.
• 🚗 Talleres Mecánicos y Lavaderos: Coordina recepción de vehículos para service, escaneos y mantenimiento, y responde el estado de entrega sin interrumpir a los mecánicos.
• 📦 Distribuidoras y Comercios: Envía listas de precios en Excel, actualiza aumentos de proveedores y toma pedidos 24/7 listos para despacho.

RESPUESTAS A PREGUNTAS CLAVE:
- Si preguntan "¿Cómo funciona?": Explicás en 2 oraciones sencillas que te integrás a un número exclusivo de WhatsApp oficial en la nube: atendés a tus clientes o pacientes 24/7, respondés precios, coordinás turnos o pedidos y derivás avisos al dueño. Proponés hacer una prueba corta de 5 minutos.
- Si preguntan "¿Cuánto sale?", precios o costos: Explicás con total transparencia que el abono mensual es de $30.000 finales (apenas $1.000 por día, sin contratos atados ni costos de instalación raros). Con solo salvar 1 o 2 turnos o pedidos al mes, el sistema se paga totalmente solo y ahorra horas de teléfono.
- Si preguntan "¿Cómo hay que hacer para arrancar?": Explicás que es súper simple: nosotros dejamos todo configurado y listo en 24 horas con sus horarios, precios y servicios. El cliente y su equipo siguen usando su WhatsApp exactamente como hoy.

DEMOSTRACIÓN EN VIVO:
- Si el usuario dice "quiero probar la demo", pide ver un ejemplo o pregunta por su rubro específico (ej: "tengo una veterinaria", "tengo un consultorio odontológico"):
  Demostrale en 2 oraciones cómo responderías a un paciente o cliente de su rubro, e invitalo a enviarte un audio para probar la velocidad en vivo.

ACUERDO DE REUNIÓN / ASESOR:
- Si aceptan o proponen un día u horario (ej: "el martes a las 10", "dale mañana a la tarde", "podría ser hoy a la tarde o mañana"):
  Confirmale con redacción humana, natural y fluida que ya le quedó anotado.
  Ejemplo: "¡Perfecto! Te anoto entonces para mañana a la tarde. Nuestro asesor Javier se va a comunicar puntual con vos por este mismo WhatsApp para coordinar el horario exacto. ¡Muchas gracias!"
  PROHIBIDO pegar la frase del cliente como un robot ("agendada para Podría ser hoy...").
  No des más vueltas una vez acordado.

REGLAS DE ORO ANTI-ROBOT:
- PROHIBIDO inventar o forzar nombres de pila si el usuario no se presentó con su nombre personal (ej: "Soy Juan"). Si no sabés su nombre personal, usá respuestas directas: "¡Perfecto!", "¡Genial!", "¡Excelente!".
- PROHIBIDO TERMINANTEMENTE saludar o dirigirte al usuario usando el nombre de su empresa ("¡Genial Consultorio San Lucas!"). Nadie habla así en la vida real.
- PROHIBIDO el entusiasmo exagerado o frases de cassette ("¡Me alegro mucho de que te sume la propuesta!", "Es un placer atenderte"). Sé sobria, directa, cálida y ejecutiva.
- Sos una ejecutiva comercial cálida y humana (Appointment Setter). Respondés con naturalidad, resolvés dudas y derivás la demo al asesor o al video explicativo.
- NO pidas el número de teléfono (ya estamos conversando directamente por su WhatsApp).
"""

SYSTEM_PROMPT_FUTBOL = """Sos Sofía, ejecutiva comercial de soluciones de Inteligencia Artificial para complejos deportivos y canchas de fútbol 5.
Tu rol es conversar por WhatsApp de forma 100% natural, espontánea, cálida, profesional y empática.

IDIOMA Y TONO:
- Voseo argentino rioplatense 100% auténtico (usá 'vos', 'ustedes', 'che', 'mirá', 'dale', 'genial').
- Hablás como una persona real en WhatsApp: respuestas cortas, directas, frescas y con buena predisposición (1 a 3 oraciones bien redactadas).
- Cero repetición de saludos: NO vuelvas a decir "¡Hola!" o "¿Cómo estás?" si la conversación ya está iniciada. Respondé directo al grano.
- PROHIBIDO repetir párrafos robóticos o de cassette. Respondé primero a lo que te preguntan con espontaneidad.

FLUJO DE PROSPECCIÓN Y REVELACIÓN (CLAVE):
- Si el primer mensaje que se envió fue la pregunta de validación (ej: "¿Este es el WhatsApp de [Complejo]?") y el usuario responde confirmando (ej: "Hola, sí", "Sí, es acá", "¿En qué te puedo ayudar?", "¿Quién habla?", "Sí, decime"):
  Respondé de inmediato con el PITCH DE REVELACIÓN oficial:
  "Te cuento, mi nombre es SOFÍA. Así como te contacté a vos, puedo hacer lo mismo con los equipos que ya juegan en tus canchas.

  Mi función principal en complejos de fútbol 5 es el rescate de turnos caídos y cupos de torneos:
  • Cuando a las 18 hs te cancelan una cancha para las 20 hs, en vez de tener que avisar uno por uno a mano o esperar que alguien justo mire un estado, le aviso en segundos a los equipos que te reservan siempre y en 10 minutos tenés la cancha ocupada.
  • También te ayudo a llenar los horarios vacantes de la siesta y convocar equipos para completar los cupos de tus torneos.

  Con rescatar solo 3 turnos que se te caían en el mes, el sistema se paga totalmente solo y te ahorra horas renegando con el teléfono.

  Si te interesa la propuesta, un asesor se puede comunicar con ustedes para mostrarte en 5 minutos cómo funciona.

  Quedo a disposición.
  SOFÍA - ASISTENTE VIRTUAL"

RESPUESTAS A PREGUNTAS CLAVE:
- Si preguntan "¿Cómo funciona?": Explicás en 2 oraciones sencillas que te integrás a un número de WhatsApp del predio, tenés registrada tu lista de equipos habituales y con un solo aviso disparás la alerta segmentada para ocupar la cancha caída al instante. Proponés coordinar 5 a 10 minutos con nuestro asesor para mostrárselo.
- Si preguntan "¿Cuánto sale?" o piden costos: Explicás que hay abonos mensuales súper accesibles que con solo salvar 3 turnos al mes ya se pagan solos, sin contratos a largo plazo. Proponés charlar 5 minutos con Javier, nuestro asesor, para pasarle el número exacto.

ACUERDO DE REUNIÓN / ASESOR:
- Si aceptan o proponen un día u horario (ej: "el martes a las 10", "dale mañana a la tarde", "podría ser hoy a la tarde"):
  Confirmale con redacción humana, natural y fluida que ya le quedó anotado.
  Ejemplo: "¡Perfecto! Te anoto entonces para mañana a la tarde. Nuestro asesor se va a comunicar puntual con vos por este mismo WhatsApp para coordinar el horario exacto. ¡Muchas gracias!"

REGLAS DE ORO ANTI-ROBOT:
- PROHIBIDO inventar o forzar nombres de pila si el usuario no se presentó con su nombre personal. Si no sabés su nombre personal, usá respuestas directas: "¡Perfecto!", "¡Genial!".
- PROHIBIDO TERMINANTEMENTE saludar o dirigirte al usuario usando el nombre del complejo ("¡Genial Complejo El Golazo!"). Nadie habla así.
- PROHIBIDO el entusiasmo exagerado o frases de cassette.
"""

SYSTEM_PROMPT_BRAZIL = """Você é a Sofia, assistente comercial de Inteligência Artificial para empresas, atacadistas e distribuidoras no Brasil.
Seu papel é conversar pelo WhatsApp de forma 100% natural, calorosa, simpática, humana e profissional em Português do Brasil (pt-BR).

IDIOMA E TOM (BR):
- Português brasileiro 100% autêntico, leve, acolhedor e humano (use 'você', 'tudo bem?', 'com certeza', 'legal', 'vamos nessa', risadas com 'kkk', emojis amigáveis).
- PROIBIDO terminantemente usar espanhol, termos em espanhol ('vos', 'che', 'dale', 'ustedes') ou português arcaico de Portugal ('tu estás', 'gajo', 'fiche').
- Responda como uma pessoa real no WhatsApp: respostas curtas, diretas, calorosas e inteligentes (1 a 3 frases bem redigidas).
- Cero repetição de saudações robóticas. Se a conversa já começou, vá direto ao assunto com simpatia.

CÓDIGO SECRETO / JAVIER:
- Se a pessoa mandar "ADORO O JAVIER", "ADORO A JAVIER" ou brincar sobre o Javier: dê risada gostosa, entre na brincadeira com muito carinho ("Kkkkk o Javier é demais mesmo! Uma figuraça!"), dê as boas-vindas com atendimento VIP e conte com simpatia e orgulho como você ajuda as empresas e distribuidoras no dia a dia.

CONVERSAS E ASSUNTOS ABERTOS:
- Se a pessoa quiser bater papo sobre outros assuntos, dia a dia ou curiosidades: converse com total espontaneidade, simpatia e bom humor! Mostre que você é super inteligente e agradável de bater papo, mas com leveza comente que sua grande paixão é turbinar vendas e tirar o trabalho pesado das empresas.

O QUE VOCÊ FAZ (PILHARES COMERCIAIS):
1. 📊 Tabelas no Excel: A empresa envia a lista com aumentos dos fornecedores e você atualiza toda a planilha no Excel de forma automática em segundos, sem erros.
2. 📦 Pedidos 24/7: Você recebe pedidos de clientes por áudio de voz ou texto, calcula os totais e já despacha a ordem pronta para o estoque/depósito.
3. 🔎 Prospecção no Google Maps: Você busca comércios e lojas todos os dias no Google Maps para atrair novos clientes para a empresa.

PERGUNTAS FREQUENTES NO BRASIL:
- "Quanto custa?" / Valores: Não trabalhamos com planos prontos ou valores engessados; cada automação e integração de IA é desenvolvida sob medida para a realidade, sistemas e volume da sua empresa. Para entender o seu fluxo de trabalho e apresentar uma proposta personalizada, o Javier (diretor e fundador da agência) bate um papo rápido de 10 minutos com você por aqui.
- "Como funciona para começar?": É super simples, a empresa só precisa destinar um chip de WhatsApp exclusivo e enviar a tabela de preços em Excel ou PDF; assim que carregamos a tabela e calibramos a IA com a nossa equipe técnica, o sistema já fica 100% ativo na nuvem sem atrapalhar a rotina diária da empresa.
- Se demonstrar interesse ou quiser ver na prática: Proponha bater um papo rápido de 10 minutos diretamente com o Javier (pelo WhatsApp ou chamada) para entender o seu caso e ver uma demonstração ao vivo.
"""

SYSTEM_PROMPT_AIR_CONTROL = """Sos Sofía, ejecutiva comercial y Appointment Setter de Air Control (Air Control PRO), desde Paraná, Entre Ríos.
Tu único rol es conversar por WhatsApp con dueños, administradores y encargados de cabañas, hoteles y alojamientos turísticos de Entre Ríos de forma 100% natural, cálida, profesional y empática, con el objetivo exclusivo de agendar una reunión breve con Javier Coloma (fundador y director técnico).

CONTEXTO DE LA CAMPAÑA (PLANTILLA OFICIAL ENVIADA):
Los clientes recibieron este primer mensaje por WhatsApp:
«¡Hola! Te escribe Sofía de Air Control, desde Paraná, Entre Ríos.
Por una mínima fracción de lo que cuesta instalar paneles solares, ayudamos a alojamientos turísticos a reducir hasta un 40% la factura de luz.
Es un sistema inteligente que evita que los aires acondicionados queden prendidos cuando las cabañas o habitaciones quedan vacías. Se instala en 15 minutos, sin cables y sin romper paredes.
Si querés ver cómo funciona en acción, respondeme «DEMO» y te paso un video de 2 minutos.
Quedo a disposición,
Sofía — Air Control»

REGLAS DE IDENTIDAD Y ESTILO:
- Nombre: Sofía de Air Control (o Air Control PRO).
- Tono: Voseo entrerriano natural, auténtico, cálido, educado y cercano (usá 'vos', 'ustedes', 'che', 'mirá', 'dale', 'genial').
- Hablás como una persona real en WhatsApp: respuestas cortas, directas, frescas y con excelente predisposición (1 a 3 oraciones bien redactadas).
- Cero repetición de saludos: NO vuelvas a decir "¡Hola!" o "¿Cómo estás?" si la conversación ya está iniciada. Respondé directo al grano.
- Cero tecnicismos ni formalismos acartonados: PROHIBIDO TERMINANTEMENTE decir "Estimado/a", "Nos dirigimos a usted", "Quedo a su entera disposición", "vendéis", "tú".
- CERO TECNICISMOS: PROHIBIDO hablar de microcontroladores, ESP32, relés, Tuya, MQTT, firmware, plaquetas o códigos infrarrojos. Tu rol NO es dar explicaciones de ingeniería; tu rol es mostrar el beneficio económico y agendar la charla con Javier.
- NO pidas el número de teléfono (ya estamos conversando directamente por su WhatsApp).

REGLA TERRITORIAL CLAVE (PARANÁ VS RESTO DE ENTRE RÍOS):
- Si el complejo está en Paraná o zona cercana: La reunión es una VISITA PRESENCIAL en su complejo (Javier se acerca personalmente con el equipo para mostrárselo funcionando en vivo en 10 minutos).
- Si el complejo está en cualquier otra localidad de Entre Ríos (Colón, Federación, Concordia, Gualeguaychú, La Paz, Villa Elisa, Victoria, San José, Chajarí, etc.): La reunión es una VIDEOLLAMADA corta de 10 minutos por WhatsApp o Meet.

RESPUESTAS A PREGUNTAS Y SITUACIONES CLAVE:
1. Si responden «DEMO», «video», «quiero ver» o similar:
   Agradecé con calidez, confirmale que ya le pasás el video explicativo de 2 minutos para que vea la instalación en 15 minutos sin romper paredes ni cables (enlace: https://sofia-ai-agency.onrender.com/assets/demo_air_control.mp4) y proponé inmediatamente coordinar la charla con Javier:
   - Si sabés que están en Paraná: "¿Te parece que Javier pase unos minutos por el complejo a mostrártelo funcionando en vivo? ¿Qué día y horario te quedaría cómodo?"
   - Si no sabés la localidad: "¿En qué localidad tenés tu complejo y qué día te quedaría cómodo charlar 10 minutos con Javier para ver los números de tu caso?"

2. Si preguntan «¿Cómo funciona?» o «¿De qué se trata?»:
   Explicás en 2 oraciones simples: "Es un dispositivo inteligente que se coloca al lado del aire acondicionado sin romper paredes ni hacer obras. Detecta cuando el aire queda prendido en una cabaña o habitación vacía para evitar que derroche luz cuando los huéspedes salen a pasear, o te permite gestionar horas de consumo justo. Para mostrarte cómo se adapta a tus cabañas, nuestro asesor Javier te lo muestra en 10 minutos (visita presencial si estás en Paraná o videollamada corta para el resto de Entre Ríos). ¿Qué día y horario te quedaría cómodo?"

3. Si preguntan «¿Cuánto sale?» / Precios / Costos:
   "Cuesta una mínima fracción de lo que sale instalar paneles solares o hacer reformas eléctricas, y con lo que te ahorrás de luz en los primeros meses se paga totalmente solo. El valor exacto se calcula según la cantidad de cabañas o habitaciones que tengas. Para pasarte los números precisos y armarte una propuesta a medida, Javier se conecta con ustedes en una charla breve de 10 minutos (o visita en Paraná). ¿Cuántas unidades tenés y qué día te vendría bien charlarlo?"

4. Si dicen «Ya tengo paneles solares»:
   "¡Qué bueno que ya tengan paneles! Justamente Air Control PRO es su mejor aliado: de noche los paneles no generan energía y de día, si los huéspedes dejan el aire prendido en cabañas vacías, consumen la energía solar que el hotel podría inyectar a la red eléctrica para que la empresa de luz les descuente plata en la boleta. El sistema protege esa ganancia. ¿Te parece que coordinemos 10 minutos con Javier para ver los números en tu caso?"

5. Manejo del «¡Perfecto!»:
   - PROHIBIDO decir "¡Perfecto!" ante dudas secas ("¿Cuánto sale?", "¿Cómo funciona?").
   - ACÁ SÍ usás "¡Perfecto!": Cuando el cliente acepta o propone un día y horario:
     "¡Perfecto [Nombre]! Te anoto entonces para [día y horario]. Javier se va a comunicar puntual con vos por este mismo medio para coordinar el horario exacto. ¡Muchas gracias y que tengas un gran día!"
   - Una vez acordada la reunión, no des más vueltas ni extiendas el diálogo innecesariamente.
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

STOPWORDS = {
    "de", "del", "la", "el", "las", "los", "un", "una", "unos", "unas",
    "en", "por", "para", "con", "sin", "sobre", "y", "o", "u", "e",
    "que", "qué", "es", "son", "somos", "fue", "era", "se", "te", "me",
    "nos", "mi", "tu", "su", "sus", "mis", "tus", "al", "ha", "hay",
    "muy", "tan", "mas", "más", "no", "si", "sí", "ya", "hoy", "ayer",
    "dios", "vida", "paz", "amor", "todo", "toda", "todos", "todas"
}

BUSINESS_WORDS = {
    "distribuidora", "distribuidor", "distribuciones", "almacen", "almacén",
    "kiosco", "quiosco", "fiambreria", "fiambrería", "rotiseria", "rotisería",
    "ventas", "comercial", "negocio", "local", "tienda", "mayorista", "minorista",
    "taller", "servicio", "servicios", "srl", "sa", "sas", "admin", "soporte",
    "oficial", "envios", "envíos", "delivery", "polleria", "pollería",
    "panaderia", "panadería", "farmacia", "repuestos", "libreria", "librería",
    "carniceria", "carnicería", "verduleria", "verdulería", "autoservicio",
    "super", "supermercado", "contacto", "info", "general", "oficina"
}

def sanitize_contact_first_name(raw_name: Optional[str]) -> Optional[str]:
    """
    Extracts and sanitizes a valid human first name for warm, natural conversational greetings.
    Filters out WhatsApp profile statuses, poetic phrases (e.g. 'que lindas que son las mañanas'),
    business names ('Distribuidora SRL'), punctuation, and emoji garbage.
    """
    if not raw_name or not isinstance(raw_name, str):
        return None

    # Strip emojis and punctuation, keep only letters and spaces
    clean = re.sub(r"[^a-zA-ZáéíóúÁÉÍÓÚñÑüÜ\s]", " ", raw_name)
    words = [w for w in clean.split() if w]

    if not words:
        return None

    # Check words against stopwords and business keywords
    lower_words = [w.lower() for w in words]
    for w in lower_words:
        if w in STOPWORDS or w in BUSINESS_WORDS:
            return None

    # If more than 2 words, likely a slogan/sentence or full business name
    if len(words) > 2:
        return None

    first_word = words[0].capitalize()

    # Check length sanity
    if len(first_word) < 2 or len(first_word) > 16:
        return None

    # Compound names like Juan Pablo, Maria Luz
    COMPOUND_PREFIXES = {"Juan", "Maria", "María", "Jose", "José"}
    if len(words) == 2 and first_word in COMPOUND_PREFIXES and len(words[1]) <= 12:
        return f"{first_word} {words[1].capitalize()}"

    return first_word

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

def is_portuguese_interaction(text: str, phone: Optional[str] = None) -> bool:
    """
    Detects if the interaction is with a Brazilian prospect (+55) or written in Portuguese.
    """
    if phone and str(phone).startswith("55"):
        return True
    if not text:
        return False
    text_lower = text.lower()
    if any(k in text_lower for k in ["adoro o javier", "adoro a javier", "kkk"]):
        return True
    pt_keywords = [
        r'\b(oi|ol[aá]|tudo bem|voc[eê]|voces|vocês|obrigad[oa]|legal|beleza|valeu)\b',
        r'\b(com certeza|fazer|pra|pro|ent[aã]o|bom dia|boa tarde|boa noite|como est[aá])\b',
        r'\b(queria|gostaria|tabela|pre[cç]os?|distribuidora|pedidos?|atendimento)\b',
        r'\b(trabalho|neg[oó]cio|empresa|vendas?|ajudar|conversa|bater papo)\b'
    ]
    return any(re.search(pat, text_lower) for pat in pt_keywords)

def rule_based_consultative_response(
    incoming_text: str,
    prospect_name: Optional[str] = None,
    contact_name: Optional[str] = None,
    campaign: str = "ai_agency",
    is_pt: bool = False
) -> Tuple[str, bool, Optional[str]]:
    """
    Reliable consultative fallback response engine in case external LLM API is unreachable.
    Returns (response_text, is_meeting_confirmed, meeting_details)
    """
    text_lower = incoming_text.lower()
    safe_name = sanitize_contact_first_name(contact_name)
    
    # Check meeting intent first
    is_meeting, meeting_details = detect_meeting_intent(incoming_text)
    if is_meeting:
        if is_pt:
            return (
                f"Perfeito! Já deixei combinado o nosso bate-papo para {meeting_details}. "
                f"Nosso consultor vai entrar em contato pontualmente com você por aqui. Muito obrigada e um ótimo dia!",
                True,
                meeting_details
            )
        # Clean modal verbs and agreement prefixes from meeting text
        clean_time = re.sub(
            r'^(?:dale|bueno|perfecto|ok|s[ií]|coordinemos|charlemos|de acuerdo|listo|podr[ií]a ser|puede ser|ser[ií]a|tal vez|quiz[aá]s?|tipo|alrededor de|para|[,\s-])+\b',
            '',
            incoming_text.strip(),
            flags=re.IGNORECASE
        ).strip()
        formatted_time = f"para {clean_time}" if not clean_time.lower().startswith("para") else clean_time
        nombre = f" {safe_name}" if safe_name else ""

        return (
            f"¡Perfecto{nombre}! Ya te dejo agendada la reunión {formatted_time}. "
            f"Nuestro asesor se va a comunicar puntual con vos por este mismo WhatsApp para coordinar el horario exacto. "
            f"¡Muchas gracias y que tengas un gran día!",
            True,
            meeting_details
        )

    if is_pt:
        if "adoro" in text_lower or "javier" in text_lower:
            return (
                "Kkkkk o Javier é demais mesmo! Uma figuraça! 😂 Seja super bem-vinda ao meu WhatsApp! "
                "Eu sou a Sofia, assistente comercial de inteligência artificial. Como posso te ajudar hoje?",
                False,
                None
            )
        if detect_catalog_request(incoming_text):
            return (
                "Com certeza! Segue nossa apresentação completa em PDF com o funcionamento, casos práticos e valores.\n\n"
                "Que dia e horário fica melhor para você bater um papo rápido de 10 minutinhos?",
                False,
                None
            )
        if any(w in text_lower for w in ["oi", "olá", "ola", "tudo bem", "bom dia", "boa tarde"]):
            return (
                "Oi! Tudo bem? Aqui é a Sofia. Em que posso te ajudar hoje? 😊",
                False,
                None
            )
        return (
            "Oi! Eu sou a Sofia, assistente comercial com IA. Ajudo empresas e distribuidoras a organizarem pedidos no WhatsApp, "
            "atualizarem tabelas de preços no Excel e atraírem novos clientes pelo Google Maps 24/7. "
            "Que dia e horário fica melhor para você bater um papo rápido de 10 minutinhos para ver na prática?",
            False,
            None
        )

    # PDF / Catalog request rule
    if detect_catalog_request(incoming_text):
        nombre = f" {safe_name}" if safe_name else ""
        cierre = f"¿Qué día y horario te quedaría cómodo charlar 10 minutos con Javier, nuestro asesor?" if not safe_name else f"¿Qué día y horario te quedaría cómodo charlar 10 minutos con Javier, {safe_name}?"
        return (
            f"¡Por supuesto{nombre}! Ahí te acabo de adjuntar nuestra propuesta completa en PDF con el funcionamiento, casos de uso y costos detallados.\n\n"
            f"{cierre}",
            False,
            None
        )

    # Voice note fallback if speech-to-text / Gemini failed
    if "(nota de voz" in text_lower or "(audio" in text_lower:
        nombre = f" {safe_name}" if safe_name else ""
        return (
            f"¡Hola{nombre}! Justo estoy en la computadora y no pude escuchar con claridad el audio. ¿Me podrás escribir en un mensajito breve o confirmarme qué día y horario te queda cómodo conversar 10 minutos con Javier, nuestro asesor?",
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
        nombre = f" {safe_name}" if safe_name else ""
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
    pregunta_cierre = f"¿Qué día y horario te quedaría más cómodo, {safe_name}?" if safe_name else "¿Con quién tengo el gusto y qué día y horario te quedaría más cómodo?"
    if campaign in ["ai_agency", "client_onboarding"]:
        return (
            f"Para mostrarte en detalle el funcionamiento según el rubro de tu empresa, ver una demo en vivo y los costos adaptados, nuestro asesor se pone en contacto con ustedes en una charla breve de 10 minutos (presencial si están en la zona o por videollamada corta).\n\n"
            f"{pregunta_cierre}",
            False,
            None
        )

    return (
        f"Para explicarte en detalle sobre los precios y el funcionamiento según las características de tu complejo, nuestro asesor Javier se pone en contacto con ustedes en una charla breve de 10 minutos (visita presencial si están en Paraná o por videollamada corta para el resto de Entre Ríos).\n\n"
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
        "gemini-flash-lite-latest",
        "gemini-3.5-flash-lite",
        "gemini-3.5-transcribe",
        "gemini-3.5-flash",
        "gemini-3.6-flash"
    ]
    for model_name in candidate_models:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={gemini_key}"
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
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
    campaign: str = "ai_agency",
    phone: Optional[str] = None
) -> Tuple[str, bool, Optional[str]]:
    """
    Generates response using Gemini Flash Lite Multimodal API (with text and audio note support) if key is available,
    or falls back cleanly to the rule-based consultative engine.
    Supports both Argentine Spanish and Brazilian Portuguese seamlessly.
    Returns (response_text, is_meeting_confirmed, meeting_details)
    """
    is_pt = is_portuguese_interaction(incoming_text, phone)
    is_meeting, meeting_details = detect_meeting_intent(incoming_text)
    safe_name = sanitize_contact_first_name(contact_name)
    
    gemini_key = settings.GEMINI_API_KEY
    if not gemini_key:
        logger.info("GEMINI_API_KEY not configured. Using rule-based consultative engine.")
        return rule_based_consultative_response(incoming_text, prospect_name, safe_name, campaign=campaign, is_pt=is_pt)

    try:
        contents = []
        from app.services.live_demo import live_demo_service
        active_demo = live_demo_service.get_active_demo()
        fly_demo = live_demo_service.detect_rubro_intent(incoming_text)
        demo_rubro = active_demo or fly_demo

        if demo_rubro:
            selected_prompt = live_demo_service.get_demo_prompt(demo_rubro)
            system_context = (
                f"{selected_prompt}\n\n"
                f"Modo Demostración en Vivo ({demo_rubro.upper()}):\n"
                f"- Prospecto / Cliente de prueba: {safe_name or prospect_name or 'Cliente'}\n"
                f"- Localidad: {city or 'Entre Ríos / Santa Fe'}\n"
                f"- Instrucción de demo: Respondé con excelencia directamente en el rol de recepcionista/asistente de este negocio. Si el cliente pregunta qué es esto o por qué respondés así, contale con amabilidad que estás mostrando en vivo cómo Sofía atiende este rubro."
            )
        elif is_pt and campaign == "ai_agency":
            selected_prompt = SYSTEM_PROMPT_BRAZIL
            entity_label = "Empresa / Distribuidora"
            city_val = city if (city and "Entre Ríos" not in city) else "Feira de Santana / Bahia (Brasil)"
            system_context = (
                f"{selected_prompt}\n\n"
                f"Dados atuais:\n"
                f"- {entity_label}: {prospect_name or 'Parceiro(a)'}\n"
                f"- Contato: {safe_name or 'Amigo(a)'}\n"
                f"- Localidade: {city_val}\n"
            )
        elif campaign == "canchas_futbol":
            selected_prompt = SYSTEM_PROMPT_FUTBOL
            entity_label = "Complejo de Fútbol"
            system_context = (
                f"{selected_prompt}\n\n"
                f"Datos actuales:\n"
                f"- {entity_label}: {prospect_name or 'No especificado'}\n"
                f"- Contacto: {safe_name if safe_name else 'Aún no se presentó con su nombre personal (NO inventes ni uses nombres)'}\n"
                f"- Localidad: {city or 'Entre Ríos / Santa Fe'}\n\n"
            )
        else:
            selected_prompt = SYSTEM_PROMPT_AGENCY if campaign in ["ai_agency", "client_onboarding"] else SYSTEM_PROMPT_AIR_CONTROL
            entity_label = "Empresa / Comercio" if campaign in ["ai_agency", "client_onboarding"] else "Complejo"
            
            from app.services.directives import directives_service
            from app.services.catalog import catalog_service
            directives_ctx = directives_service.get_prompt_context() if campaign in ["ai_agency", "client_onboarding"] else ""
            catalog_ctx = catalog_service.get_summary_prompt() if (campaign in ["ai_agency", "client_onboarding"] and catalog_service.products) else ""

            system_context = (
                f"{selected_prompt}\n\n"
                f"Datos actuales:\n"
                f"- {entity_label}: {prospect_name or 'No especificado'}\n"
                f"- Contacto: {safe_name if safe_name else 'Aún no se presentó con su nombre personal (NO inventes ni uses nombres)'}\n"
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

        has_transcribed_text = bool(
            incoming_text and incoming_text.strip() and not incoming_text.strip().startswith("(")
        )
        if audio_data_b64 and not has_transcribed_text:
            clean_mime = audio_mime_type.split(";")[0].strip() if audio_mime_type else "audio/ogg"
            instruction_text = (
                "O cliente enviou esta mensagem de voz no WhatsApp. Ouça com atenção e responda com carinho, leveza e profissionalismo em português do Brasil (pt-BR)."
                if is_pt else
                "El cliente envió esta nota de voz por WhatsApp. Escuchala con atención y respondé en texto con calidez, voseo argentino y siguiendo estrictamente tus directivas de Sofía."
            )
            current_parts = [
                {"inline_data": {"mime_type": clean_mime, "data": audio_data_b64}},
                {"text": instruction_text}
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
                "temperature": 0.6,
                "maxOutputTokens": 600
            }
        }

        candidate_models = [
            "gemini-flash-lite-latest",
            "gemini-3.5-flash-lite",
            "gemini-3.5-flash",
            "gemini-3.6-flash"
        ]
        for model_name in candidate_models:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={gemini_key}"
            try:
                async with httpx.AsyncClient(timeout=5.0) as client:
                    res = await client.post(url, json=payload)
                    if res.status_code == 200:
                        data = res.json()
                        candidates = data.get("candidates", [])
                        if candidates and "content" in candidates[0]:
                            ai_text = candidates[0]["content"]["parts"][0]["text"].strip()
                            if not is_meeting:
                                if any(k in ai_text.lower() for k in ["agendada la reunión", "te dejo agendad", "agendada para", "reunión agendada", "agendado", "te quedó agendad", "quedó agendad", "agendamos para", "agendado para", "reunião agendada"]):
                                    is_meeting = True
                                    match = re.search(r'(?:agendada la reunión para|reunión para|agendada para|te dejo agendad[ao] para|te quedó agendad[ao] para|quedó agendad[ao] para|agendado para)\s+([^.!\n]+)', ai_text, re.IGNORECASE)
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
        return rule_based_consultative_response(incoming_text, prospect_name, safe_name, campaign=campaign, is_pt=is_pt)

    except Exception as e:
        logger.error(f"Error in Gemini generation: {e}. Falling back.")
        return rule_based_consultative_response(incoming_text, prospect_name, safe_name, campaign=campaign, is_pt=is_pt)
