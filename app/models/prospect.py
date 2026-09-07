from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, Text, DateTime
from app.database import Base

def utc_now():
    return datetime.now(timezone.utc)

class Prospect(Base):
    """
    Model representing prospects, leads and clients contacted by Sofía,
    the autonomous B2B AI Sales Representative.
    """
    __tablename__ = "prospects"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)                            # e.g. "Distribuidora Río Paraná"
    contact_name = Column(String, nullable=True)                  # e.g. "Martín"
    phone = Column(String, unique=True, index=True)               # e.g. "5493434991122"
    city = Column(String, nullable=True)                         # e.g. "Paraná", "Santa Fe"
    units_count = Column(Integer, nullable=True)                 # Optional units/branches count
    status = Column(String, default="pending", index=True)        # pending, contacted, in_conversation, meeting_scheduled, human_takeover, not_interested
    campaign = Column(String, default="ai_agency", index=True)    # ai_agency, air_control, etc.
    business_type = Column(String, nullable=True)               # e.g. "distribuidora", "mayorista", "ferreteria"
    notes = Column(Text, nullable=True)
    conversation_history = Column(Text, default="[]")             # JSON array of message objects
    meeting_details = Column(Text, nullable=True)                 # e.g. "Miércoles 15:00 hs"
    meeting_scheduled_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

class WebhookEvent(Base):
    __tablename__ = "webhook_events"

    id = Column(Integer, primary_key=True, index=True)
    payload = Column(Text)
    created_at = Column(DateTime, default=utc_now)
