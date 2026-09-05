import urllib.parse
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

def generate_google_calendar_link(
    summary: str,
    description: str,
    location: str = "Paraná • Videollamada",
    meeting_str: Optional[str] = None
) -> str:
    """
    Generates a 1-click Google Calendar web link (works natively on Android, iPhone and PC)
    pre-filling title, description, location, and advisor notes.
    """
    params = {
        "action": "TEMPLATE",
        "text": summary,
        "details": description,
        "location": location
    }

    # Clean encoded URL
    query_string = urllib.parse.urlencode(params)
    return f"https://calendar.google.com/calendar/render?{query_string}"

def generate_ics_calendar_content(
    summary: str,
    description: str,
    location: str = "Paraná • Videollamada",
    organizer_email: str = "sofia@aiagency.com",
    duration_minutes: int = 15
) -> str:
    """
    Generates an iCalendar (RFC 5545) .ics file string compatible with Google Calendar,
    Apple Calendar, and Microsoft Outlook.
    """
    now_utc = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    # Default to tomorrow + 1 day at 11:00 hs UTC-3 (14:00 UTC)
    start_time = (datetime.now(timezone.utc) + timedelta(days=1)).replace(hour=14, minute=0, second=0)
    end_time = start_time + timedelta(minutes=duration_minutes)

    dt_start = start_time.strftime("%Y%m%dT%H%M%SZ")
    dt_end = end_time.strftime("%Y%m%dT%H%M%SZ")

    ics_content = (
        "BEGIN:VCALENDAR\r\n"
        "VERSION:2.0\r\n"
        "PRODID:-//Sofia AI Agency//B2B Appointment Setter//ES\r\n"
        "CALSCALE:GREGORIAN\r\n"
        "METHOD:REQUEST\r\n"
        "BEGIN:VEVENT\r\n"
        f"UID:sofia-meeting-{datetime.now(timezone.utc).timestamp()}@sofia-ai-agency.onrender.com\r\n"
        f"DTSTAMP:{now_utc}\r\n"
        f"DTSTART:{dt_start}\r\n"
        f"DTEND:{dt_end}\r\n"
        f"SUMMARY:{summary}\r\n"
        f"DESCRIPTION:{description.replace(chr(10), '\\n')}\r\n"
        f"LOCATION:{location}\r\n"
        f"ORGANIZER;CN=Sofía AI Agency:mailto:{organizer_email}\r\n"
        "STATUS:CONFIRMED\r\n"
        "BEGIN:VALARM\r\n"
        "TRIGGER:-PT15M\r\n"
        "ACTION:DISPLAY\r\n"
        "DESCRIPTION:Recordatorio de Reunión Comercial con Sofía AI Agency\r\n"
        "END:VALARM\r\n"
        "END:VEVENT\r\n"
        "END:VCALENDAR\r\n"
    )
    return ics_content
