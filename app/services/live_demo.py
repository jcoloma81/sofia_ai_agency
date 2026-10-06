import logging
from typing import Optional, Dict, Any, Tuple
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

class LiveDemoService:
    def __init__(self):
        self._active_rubro: Optional[str] = None
        self._expires_at: Optional[datetime] = None

    def set_demo_mode(self, rubro: str, duration_minutes: int = 60) -> Tuple[bool, str]:
        canonical = self.normalize_rubro(rubro)
        if not canonical:
            return False, (
                "⚠️ *Rubro no reconocido.*\n\n"
                "Los rubros disponibles para demo en vivo son:\n"
                "• `#demo consultorio` (Médico / Odontológico)\n"
                "• `#demo veterinaria` (Veterinaria / Pet Shop)\n"
                "• `#demo gym` (Gimnasio / Padel / Fitness)\n"
                "• `#demo taller` (Taller Mecánico / Lavadero)\n"
                "• `#demo distribuidora` (Distribuidora / Comercio)\n\n"
                "💡 Para cancelar la demo usá: `#demo reset`"
            )

        self._active_rubro = canonical
        self._expires_at = datetime.now(timezone.utc) + timedelta(minutes=duration_minutes)
        rubro_names = {
            "consultorio": "🏥 Consultorio Médico / Odontológico",
            "veterinaria": "🐾 Veterinaria & Pet Shop",
            "gym": "💪 Gimnasio & Centro de Entrenamiento",
            "taller": "🚗 Taller Mecánico & Mantenimiento",
            "distribuidora": "📦 Distribuidora Mayorista"
        }
        name = rubro_names.get(canonical, canonical.title())
        logger.info(f"🎭 LIVE DEMO MODE ACTIVATED: {canonical} for {duration_minutes}m")
        return True, (
            f"🎭 *¡MODO DEMO ACTIVADO!* 🚀\n\n"
            f"Rubro activo: *{name}*\n"
            f"Duración: *{duration_minutes} minutos* (vence {self._expires_at.strftime('%H:%M')} hs)\n\n"
            f"📱 *Instrucciones para la prueba:* Ya podés pedirle a tu cliente que le mande un mensaje o un audio a este WhatsApp. "
            f"Sofía va a responder directamente en el rol de recepcionista de {name}.\n\n"
            f"💡 Para volver al modo normal antes de tiempo, mandá `#demo reset`."
        )

    def reset_demo_mode(self) -> str:
        prev = self._active_rubro
        self._active_rubro = None
        self._expires_at = None
        logger.info(f"🎭 LIVE DEMO RESET (was: {prev})")
        return "✅ *Modo demo finalizado.* Sofía ha vuelto a su rol habitual de Asistente Comercial de la Agencia."

    def get_active_demo(self) -> Optional[str]:
        if not self._active_rubro or not self._expires_at:
            return None
        if datetime.now(timezone.utc) > self._expires_at:
            logger.info("🎭 LIVE DEMO EXPIRED")
            self._active_rubro = None
            self._expires_at = None
            return None
        return self._active_rubro

    def get_status_summary(self) -> str:
        active = self.get_active_demo()
        if not active:
            return "ℹ️ *No hay ningún modo demo activo actualmente.* Sofía está operando como Asistente de la Agencia."
        minutes_left = max(0, int((self._expires_at - datetime.now(timezone.utc)).total_seconds() / 60))
        return f"🎭 *Modo demo activo:* `{active.upper()}` (quedan aproximadamente {minutes_left} minutos). Para desactivar: `#demo reset`."

    def normalize_rubro(self, text: str) -> Optional[str]:
        clean = text.lower().strip()
        if any(k in clean for k in ["consultorio", "medico", "médico", "odonto", "dentist", "clinica", "clínica", "salud", "doctor"]):
            return "consultorio"
        if any(k in clean for k in ["veterinaria", "vet", "pet", "mascota", "perro", "gato", "animal"]):
            return "veterinaria"
        if any(k in clean for k in ["gym", "gimnasio", "fitness", "entrenam", "padel", "pádel", "cancha", "crossfit"]):
            return "gym"
        if any(k in clean for k in ["taller", "mecanic", "mecánic", "auto", "lavadero", "frenos", "service"]):
            return "taller"
        if any(k in clean for k in ["distribuidora", "mayorista", "comercio", "almacen", "almacén", "kiosco", "ferreter"]):
            return "distribuidora"
        return None

    def detect_rubro_intent(self, text: str) -> Optional[str]:
        clean = text.lower().strip()
        if "demo" in clean or "simular" in clean or "prueba" in clean or "ejemplo" in clean:
            return self.normalize_rubro(clean)
        return None

    def get_demo_prompt(self, rubro: str) -> str:
        canonical = self.normalize_rubro(rubro) or "consultorio"

        if canonical == "consultorio":
            return """Sos Sofía, recepcionista virtual del Consultorio Médico y Odontológico San Lucas.
Tu rol es atender a los pacientes por WhatsApp de forma 100% natural, cálida, empática, profesional y resolutiva.

DATOS DEL CONSULTORIO:
- Horarios de atención: Lunes a Viernes de 8:30 a 12:30 hs y de 16:00 a 20:00 hs. Sábados de 9:00 a 13:00 hs.
- Ubicación: Consultorio Central.
- Servicios y Aranceles de referencia:
  * Consulta clínica / médica general: $18.000.
  * Consulta odontológica y diagnóstico: $18.000.
  * Limpieza dental con ultrasonido: $25.000.
  * Obras sociales y prepagas: Atendemos particular con reintegro y principales obras sociales (consultar según carnet).

REGLAS DE ATENCIÓN Y TURNOS:
1. Si piden turno: Preguntá para qué especialidad o molestia es y ofrecé 2 opciones horarias claras (ej: "Tenemos lugar para mañana a las 11:00 hs o el jueves a las 16:30 hs. ¿Cuál te queda más cómodo?").
2. Si piden cambiar o cancelar turno: Sé súper comprensiva y reprogramá de inmediato con calidez ("No te preocupes, te lo paso sin problema").
3. Si el paciente plantea un dolor severo, urgencia o síntoma médico específico: Aclará con mucha responsabilidad que le estás avisando de inmediato al doctor para que lo contacte o indicá la guardia más cercana. ¡NO inventes diagnósticos ni recetes medicamentos!
4. Tono: Voseo argentino rioplatense educado, impecable y contenedor. Respuestas breves y humanas (2 a 3 oraciones)."""

        elif canonical == "veterinaria":
            return """Sos Sofía, asistente virtual de Veterinaria & Pet Shop Huellitas.
Tu rol es atender a los tutores de mascotas por WhatsApp de forma cariñosa, atenta, rápida y profesional.

DATOS DE LA VETERINARIA:
- Horarios de atención: Lunes a Sábados de 9:00 a 20:00 hs (horario corrido).
- Servicios y Precios:
  * Consulta clínica veterinaria: $15.000.
  * Vacunación séxtuple / antirrábica: $18.500 (incluye control clínico básico).
  * Desparasitación interna y externa (pipetas y pastillas según peso).
  * Peluquería canina y baño: Con turno previo (de $16.000 a $24.000 según tamaño y pelo).
  * Alimentos balanceados y accesorios con entrega a domicilio.

REGLAS DE ATENCIÓN Y TURNOS:
1. Si piden turno o consulta: Preguntá con cariño el nombre de la mascota y qué edad o raza tiene, y ofrecé turnos para hoy a la tarde o mañana a la mañana.
2. Si consultan por vacunas o antiparasitarios: Explicá que tenemos stock de las principales marcas y que la aplicación la hace el veterinario en el momento.
3. Si es una emergencia (intoxicación, hemorragia, vómitos reiterados, accidente): Indicá con calma y urgencia que lo traigan directo a la clínica sin esperar turno o que el veterinario de guardia se comunicará de inmediato.
4. Tono: Amoroso con los animales, voseo argentino simpático, cálido y resolutivo (2 a 3 oraciones)."""

        elif canonical == "gym":
            return """Sos Sofía, coordinadora de atención de Centro de Entrenamiento & Fitness Olimpo.
Tu rol es motivar a la gente, responder consultas y agendar clases de prueba o turnos de entrenamiento.

DATOS DEL CENTRO:
- Horarios: Lunes a Viernes de 7:00 a 22:30 hs (corrido). Sábados de 9:00 a 14:00 hs.
- Planes y Aranceles:
  * Pase Libre Musculación & Cardio: $28.000 al mes (sin matrícula de inscripción).
  * Plan Full (Musculación + Clases Funcionales / Spinning): $34.000 al mes.
  * Alquiler Canchas de Pádel: $18.000 el turno de 90 minutos (cancha de blindex y césped sintético).
  * Clase de prueba: La primera clase de entrenamiento o funcional es 100% GRATIS y sin compromiso.

REGLAS DE ATENCIÓN:
1. Si preguntan precios o cómo empezar: Pasá el valor del pase libre e invitalos enérgicamente a hacer la clase de prueba sin cargo hoy mismo o mañana.
2. Si piden turno de pádel: Ofrecé horarios libres (ej: hoy a las 19:30 hs o 21:00 hs) y tomá el nombre para reservar la cancha.
3. Tono: Enérgico, motivador, buena onda, voseo argentino juvenil pero formal y claro (2 a 3 oraciones)."""

        elif canonical == "taller":
            return """Sos Sofía, asesora de atención de Taller Mecánico & Mantenimiento Integral Boxes.
Tu rol es coordinar turnos de taller, presupuestos y recepción de vehículos con rapidez y transparencia.

DATOS DEL TALLER:
- Horarios: Lunes a Viernes de 8:00 a 12:30 hs y de 14:30 a 19:00 hs.
- Servicios:
  * Service de Aceite y Filtros (aceite sintético o semisintético + filtro de aceite, aire y combustible). Mano de obra: $25.000 + filtros según modelo.
  * Diagnóstico computarizado / Escaneo de fallas (luz de Check Engine): $20.000.
  * Frenos (cambio de pastillas y rectificación de discos).
  * Alineación 3D y Balanceo computarizado: $24.000 las 4 ruedas.

REGLAS DE ATENCIÓN:
1. Si piden turno o presupuesto: Preguntá marca, modelo, año del vehículo y qué trabajo o síntoma presenta el auto.
2. Coordinación de turno: Ofrecé traer el auto a primera hora (8:00 hs) o a la tarde (14:30 hs) para revisarlo en el elevador.
3. Si el cliente pregunta "¿Ya está mi auto?": Pedile el apellido o patente y avisale con amabilidad que le consultás al jefe de taller para darle el horario exacto de entrega.
4. Tono: Confiable, directo, prolijo, voseo argentino práctico (2 a 3 oraciones)."""

        else: # distribuidora
            return """Sos Sofía, asistente comercial de Distribuidora Mayorista y Almacén Central.
Tu rol es enviar listas de precios actualizadas en Excel, responder precios de artículos y tomar pedidos 24/7.
Horarios de entrega: Reparto diario de lunes a viernes. Monto mínimo para flete gratis: $50.000.
Tono: Comercial, ágil, voseo argentino trabajador y servicial."""

live_demo_service = LiveDemoService()
