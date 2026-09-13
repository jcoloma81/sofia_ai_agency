import os
import sys
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# Ensure project root is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.database import Base, run_auto_migrations
from app.models.prospect import Prospect, SupplierDraftOrder, MerchantProduct, WebhookEvent

TEST_DATABASE_URL = "sqlite:///:memory:"

test_engine = create_engine(
    TEST_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)

@pytest.fixture(scope="session", autouse=True)
def setup_test_database():
    Base.metadata.create_all(bind=test_engine)
    run_auto_migrations(test_engine)
    yield
    Base.metadata.drop_all(bind=test_engine)


@pytest.fixture(autouse=True)
def reset_catalog_to_base():
    from app.services.catalog import catalog_service
    sample_csv = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "app", "data", "sample_catalog.csv"))
    if os.path.exists(sample_csv):
        with open(sample_csv, "r", encoding="utf-8") as f:
            catalog_service.load_from_csv(f.read(), source_name="Catálogo Base")
    yield


@pytest.fixture(autouse=True)
def prevent_real_external_whatsapp_calls(monkeypatch):
    """
    Air-gap safety shield for tests:
    Guarantees that no test execution can EVER send real WhatsApp messages or templates to Meta or users.
    """
    from unittest.mock import AsyncMock
    monkeypatch.setattr("app.services.whatsapp._send_single_whatsapp_message", AsyncMock(return_value=True))
    monkeypatch.setattr("app.services.whatsapp.send_whatsapp_template", AsyncMock(return_value=True))
    monkeypatch.setattr("app.services.whatsapp.send_whatsapp_document", AsyncMock(return_value=True))
    monkeypatch.setattr("app.services.whatsapp.send_whatsapp_audio", AsyncMock(return_value=True))
    yield

@pytest.fixture
def db():
    from app.models.prospect import SupplierDraftOrder, MerchantProduct
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.query(Prospect).delete()
        session.query(SupplierDraftOrder).delete()
        session.query(MerchantProduct).delete()
        session.commit()
        session.close()


