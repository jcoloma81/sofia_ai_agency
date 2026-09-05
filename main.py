import logging
from datetime import datetime, timezone
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.database import Base, engine
from app.routers.webhook import router as webhook_router
from app.routers.outreach import router as outreach_router
from app.config.settings import settings

# Initialize logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("sofia_ai_agency")

# Create database tables automatically
Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="Sofía AI Agency — Autonomous B2B SDR Platform",
    description="Autonomous B2B outbound & inbound sales development representative powered by Google Gemini Flash Lite Multimodal, Whapi Cloud, and Intelligent Lead Scraping.",
    version="1.0.0"
)

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Health endpoint
@app.get("/health")
def health_check():
    return {
        "status": "healthy",
        "platform": "sofia_ai_agency",
        "version": "1.0.0",
        "timestamp": datetime.now(timezone.utc).isoformat()
    }

# Root welcome
@app.get("/")
def root():
    return {
        "message": "Bienvenido a Sofía AI Agency Platform",
        "docs_url": "/docs",
        "health_url": "/health",
        "agent": "Sofía B2B SDR"
    }

# Mount Webhook & Outreach Routers
# Primary paths
app.include_router(webhook_router, tags=["WhatsApp Webhook"])
app.include_router(webhook_router, prefix="/api/v1/webhook", tags=["WhatsApp Webhook v1"])
app.include_router(outreach_router, prefix="/api/v1/outreach", tags=["Outreach v1"])

# Backward compatibility routes (for existing scripts and tests)
app.include_router(webhook_router, prefix="/api/v1/prospecting", tags=["Prospecting Compatibility"])
app.include_router(outreach_router, prefix="/api/v1/prospecting", tags=["Prospecting Compatibility"])

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
