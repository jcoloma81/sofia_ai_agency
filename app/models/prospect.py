from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, Text, DateTime, Float, Boolean
from app.database import Base

def utc_now():
    return datetime.now(timezone.utc)

class Prospect(Base):
    """
    Model representing prospects, leads, suppliers and clients contacted by Sofía,
    the autonomous B2B AI Sales Representative.
    Multi-tenant: merchant_phone isolates contacts and suppliers per merchant.
    """
    __tablename__ = "prospects"

    id = Column(Integer, primary_key=True, index=True)
    merchant_phone = Column(String, index=True, nullable=True)   # E.164 phone of merchant who owns this contact/supplier
    name = Column(String, index=True)                            # e.g. "Distribuidora Río Paraná"
    contact_name = Column(String, nullable=True)                  # e.g. "Martín"
    phone = Column(String, index=True)                           # e.g. "5493434991122" (not globally unique so multiple merchants can share suppliers)
    city = Column(String, nullable=True)                         # e.g. "Paraná", "Santa Fe"
    units_count = Column(Integer, nullable=True)                 # Optional units/branches count
    status = Column(String, default="pending", index=True)        # pending, contacted, in_conversation, meeting_scheduled, human_takeover, not_interested
    campaign = Column(String, default="ai_agency", index=True)    # ai_agency, air_control, supplier, client_onboarding, etc.
    business_type = Column(String, nullable=True)               # e.g. "distribuidora", "mayorista", "ferreteria", "proveedor"
    notes = Column(Text, nullable=True)
    conversation_history = Column(Text, default="[]")             # JSON array of message objects
    meeting_details = Column(Text, nullable=True)                 # e.g. "Miércoles 15:00 hs"
    meeting_scheduled_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

class SupplierDraftOrder(Base):
    """
    Represents an in-progress unconfirmed draft basket (pedidos borrador)
    for a merchant with a specific supplier.
    Ensures 100% tenant isolation: each merchant's cart is private and safe from collisions.
    """
    __tablename__ = "supplier_draft_orders"

    id = Column(Integer, primary_key=True, index=True)
    merchant_phone = Column(String, index=True, nullable=False)   # E.164 phone of merchant
    supplier_key = Column(String, index=True, nullable=False)     # e.g. "distribuidora_alem"
    supplier_name = Column(String, nullable=False)                # e.g. "Distribuidora Alem"
    items = Column(Text, default="[]")                            # JSON array of {product_name, quantity, unit_price}
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

class MerchantProduct(Base):
    """
    Product from a supplier's price list associated with a specific merchant.
    Allows each merchant to have their own price lists, costs, and comparisons without cross-contamination.
    """
    __tablename__ = "merchant_products"

    id = Column(Integer, primary_key=True, index=True)
    merchant_phone = Column(String, index=True, nullable=False)   # E.164 phone of merchant
    supplier_name = Column(String, index=True, nullable=False)    # e.g. "Distribuidora Alem"
    name = Column(String, index=True, nullable=False)             # e.g. "Disco de corte 115mm"
    price = Column(Float, nullable=False, default=0.0)
    cost_price = Column(Float, nullable=True)
    presentation = Column(String, default="Unidad")
    category = Column(String, default="General")
    code = Column(String, nullable=True, index=True)
    in_stock = Column(Boolean, default=True)
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

class WebhookEvent(Base):
    __tablename__ = "webhook_events"

    id = Column(Integer, primary_key=True, index=True)
    payload = Column(Text)
    created_at = Column(DateTime, default=utc_now)

