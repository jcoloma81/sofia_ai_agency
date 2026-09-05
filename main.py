import logging
from datetime import datetime, timezone
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

import os
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.database import Base, engine
from app.routers.webhook import router as webhook_router
from app.routers.outreach import router as outreach_router
from app.routers.dashboard import router as dashboard_router
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

# Mount Assets Directory
assets_dir = os.path.join(os.path.dirname(__file__), "assets")
if os.path.exists(assets_dir):
    app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

# Health endpoint
@app.get("/health")
def health_check():
    return {
        "status": "healthy",
        "platform": "sofia_ai_agency",
        "version": "1.0.0",
        "timestamp": datetime.now(timezone.utc).isoformat()
    }

# Executive Web Dashboard
@app.get("/", response_class=FileResponse)
@app.get("/dashboard", response_class=FileResponse)
def serve_dashboard():
    dashboard_path = os.path.join(os.path.dirname(__file__), "app", "static", "dashboard.html")
    return FileResponse(dashboard_path)

# Mount Webhook, Outreach & Dashboard Routers
app.include_router(dashboard_router, tags=["Executive Dashboard"])
app.include_router(webhook_router, tags=["WhatsApp Webhook"])
app.include_router(webhook_router, prefix="/api/v1/webhook", tags=["WhatsApp Webhook v1"])
app.include_router(outreach_router, prefix="/api/v1/outreach", tags=["Outreach v1"])

# Backward compatibility routes
app.include_router(webhook_router, prefix="/api/v1/prospecting", tags=["Prospecting Compatibility"])
app.include_router(outreach_router, prefix="/api/v1/prospecting", tags=["Prospecting Compatibility"])

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
