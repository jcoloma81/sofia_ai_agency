import random
import logging
from datetime import datetime, timezone
try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo

from sqlalchemy.orm import Session
from sqlalchemy import func
from app.models.prospect import Prospect

logger = logging.getLogger(__name__)

# Argentine Timezone (America/Argentina/Buenos_Aires) UTC-3
ARG_TZ = ZoneInfo("America/Argentina/Buenos_Aires")

# Safety Configuration
BUSINESS_START_HOUR = 9     # 09:00 AM
BUSINESS_END_HOUR = 18       # 06:00 PM (18:00)
ALLOWED_WEEKDAYS = [0, 1, 2, 3, 4]  # Monday (0) to Friday (4). Saturday (5) can be added if needed.
MAX_DAILY_OUTREACH = 15      # Safe maximum cold outreaches per day

def get_current_argentine_time() -> datetime:
    """Returns current local time in Buenos Aires / Entre Ríos."""
    return datetime.now(timezone.utc).astimezone(ARG_TZ)

def is_within_business_hours() -> bool:
    """
    Checks if current time is within safe commercial prospecting hours:
    Monday to Friday, between 09:00 and 18:00 Argentine time.
    """
    now_arg = get_current_argentine_time()
    weekday = now_arg.weekday()
    hour = now_arg.hour

    if weekday not in ALLOWED_WEEKDAYS:
        return False

    return BUSINESS_START_HOUR <= hour < BUSINESS_END_HOUR

def get_daily_outreaches_count(db: Session) -> int:
    """
    Calculates how many new prospects have been contacted today (in local Argentina date).
    """
    now_arg = get_current_argentine_time()
    today_start_arg = now_arg.replace(hour=0, minute=0, second=0, microsecond=0)
    today_start_utc = today_start_arg.astimezone(timezone.utc)

    count = db.query(Prospect).filter(
        Prospect.status.in_(["contacted", "in_conversation", "meeting_scheduled"]),
        Prospect.created_at >= today_start_utc
    ).count()

    return count

def validate_outreach_safety(db: Session, force: bool = False) -> tuple[bool, str]:
    """
    Validates anti-ban policies:
    1. Check daily limit (max 15/day).
    2. Check business hours (09:00 - 18:00 hs, Mon-Fri).
    """
    if force:
        return True, "Modo forzado por usuario (omite restricciones horarias y de cupo)."

    # 1. Check daily quota
    daily_count = get_daily_outreaches_count(db)
    if daily_count >= MAX_DAILY_OUTREACH:
        msg = f"Cupo diario alcanzado ({daily_count}/{MAX_DAILY_OUTREACH}). Para proteger la línea de WhatsApp, no se enviarán más prospecciones en frío hoy."
        logger.warning(msg)
        return False, msg

    # 2. Check business hours
    if not is_within_business_hours():
        now_arg = get_current_argentine_time()
        msg = (
            f"Fuera de horario comercial ({now_arg.strftime('%A %H:%M hs')}). "
            f"La prospección segura opera de lunes a viernes entre las {BUSINESS_START_HOUR}:00 y {BUSINESS_END_HOUR}:00 hs."
        )
        logger.warning(msg)
        return False, msg

    return True, f"Seguro ({daily_count}/{MAX_DAILY_OUTREACH} enviados hoy)."

def get_randomized_pacing_delay(min_seconds: int = 180, max_seconds: int = 420) -> int:
    """
    Returns a randomized human-like delay between messages (e.g. 3 to 7 minutes)
    to prevent repetitive bot cadence.
    """
    return random.randint(min_seconds, max_seconds)
