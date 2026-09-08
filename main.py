import logging
from datetime import datetime, timezone
from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware

import os
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.database import Base, engine
from app.routers.webhook import router as webhook_router
from app.routers.outreach import router as outreach_router
from app.routers.dashboard import router as dashboard_router, verify_admin_credentials
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
        "meta_configured": bool(settings.META_ACCESS_TOKEN and settings.META_PHONE_NUMBER_ID),
        "meta_phone_id": settings.META_PHONE_NUMBER_ID,
        "meta_token_suffix": settings.META_ACCESS_TOKEN[-6:] if settings.META_ACCESS_TOKEN else None,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }

# Public Landing & Commercial Proposal
@app.get("/", response_class=FileResponse)
@app.get("/propuesta", response_class=FileResponse)
@app.get("/precios", response_class=FileResponse)
def serve_propuesta():
    propuesta_path = os.path.join(os.path.dirname(__file__), "app", "static", "propuesta_comercial.html")
    return FileResponse(propuesta_path)

# Executive Web Dashboard (Restricted Admin Access)
@app.get("/dashboard", response_class=FileResponse, dependencies=[Depends(verify_admin_credentials)])
@app.get("/admin", response_class=FileResponse, dependencies=[Depends(verify_admin_credentials)])
def serve_dashboard():
    dashboard_path = os.path.join(os.path.dirname(__file__), "app", "static", "dashboard.html")
    return FileResponse(dashboard_path)

@app.get("/privacy")
def privacy_policy():
    from fastapi.responses import HTMLResponse
    html = """<!DOCTYPE html><html><head><title>Política de Privacidad - Sofía AI</title><meta charset='utf-8'></head>
    <body style='font-family:sans-serif;max-width:800px;margin:40px auto;line-height:1.6;color:#333;padding:20px;'>
    <h1>Política de Privacidad de Sofía AI Agency</h1>
    <p>Última actualización: Septiembre 2026</p>
    <p>Sofía AI Agency respeta su privacidad y protege los datos personales recopilados exclusivamente para la gestión de consultas comerciales y atención al cliente a través de la API oficial de WhatsApp.</p>
    <p>No compartimos datos personales con terceros ni comercializamos información de usuarios.</p>
    <p>Para consultas o baja de datos, contacte a: colomajavier@gmail.com</p>
    </body></html>"""
    return HTMLResponse(content=html)

@app.get("/terms")
def terms_of_service():
    from fastapi.responses import HTMLResponse
    html = """<!DOCTYPE html><html><head><title>Términos de Servicio - Sofía AI</title><meta charset='utf-8'></head>
    <body style='font-family:sans-serif;max-width:800px;margin:40px auto;line-height:1.6;color:#333;padding:20px;'>
    <h1>Términos de Servicio de Sofía AI Agency</h1>
    <p>Al interactuar con nuestros canales automatizados, usted acepta el uso de inteligencia artificial para la asistencia y coordinación de demostraciones comerciales y pedidos.</p>
    <p>Contacto: colomajavier@gmail.com</p>
    </body></html>"""
    return HTMLResponse(content=html)

# Mount Webhook, Outreach & Dashboard Routers
app.include_router(dashboard_router, tags=["Executive Dashboard"])
app.include_router(webhook_router, tags=["WhatsApp Webhook"])
app.include_router(webhook_router, prefix="/api/v1", tags=["WhatsApp Webhook v1"])
app.include_router(webhook_router, prefix="/api/v1/webhook", tags=["WhatsApp Webhook v1 Extra"])
app.include_router(outreach_router, prefix="/api/v1/outreach", tags=["Outreach v1"])

# Backward compatibility routes
app.include_router(webhook_router, prefix="/api/v1/prospecting", tags=["Prospecting Compatibility"])
app.include_router(outreach_router, prefix="/api/v1/prospecting", tags=["Prospecting Compatibility"])

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
