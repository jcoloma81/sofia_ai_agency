import logging
from datetime import datetime, timezone
from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware

import os
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.database import Base, engine, run_auto_migrations, verify_database_health
from app.routers.webhook import router as webhook_router
from app.routers.outreach import router as outreach_router
from app.routers.dashboard import router as dashboard_router, verify_admin_credentials
from app.routers.bridge import router as bridge_router
from app.routers.tenants import router as tenants_router
from app.routers.payments import router as payments_router
from app.config.settings import settings

# Initialize logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("sofia_ai_agency")

# Create database tables automatically
Base.metadata.create_all(bind=engine)
run_auto_migrations(engine)


app = FastAPI(
    title="Sofía AI Agency — Autonomous WhatsApp & Multi-Industry Business Platform",
    description="Autonomous multi-industry and B2B WhatsApp platform powered by Google Gemini 1.5 Multimodal, Official Meta WhatsApp Cloud API, and Mercado Pago.",
    version="2.0.0"
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
    db_ok = verify_database_health(engine)
    return {
        "status": "healthy" if db_ok else "degraded",
        "database": "connected" if db_ok else "unreachable",
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

# Ficha de Alta de Cliente & Relevamiento Operativo
@app.get("/alta-cliente", response_class=FileResponse)
@app.get("/onboarding", response_class=FileResponse)
@app.get("/ficha", response_class=FileResponse)
def serve_alta_cliente():
    alta_path = os.path.join(os.path.dirname(__file__), "app", "static", "ficha_alta_cliente.html")
    return FileResponse(alta_path)

# Executive Technical Architecture & Meeting Cheat Sheet
@app.get("/hoja-de-ruta", response_class=FileResponse)
@app.get("/arquitectura", response_class=FileResponse)
@app.get("/cheat-sheet", response_class=FileResponse)
def serve_hoja_de_ruta():
    doc_path = os.path.join(os.path.dirname(__file__), "docs", "hoja_de_ruta_tecnica.html")
    return FileResponse(doc_path)

# Commercial Multi-Tenant Manual & Pitch PDF for Businesses
@app.get("/manual-rubros", response_class=FileResponse)
@app.get("/guia-comercial", response_class=FileResponse)
def serve_manual_rubros_html():
    doc_path = os.path.join(os.path.dirname(__file__), "docs", "manual_comercial_sofia_rubros.html")
    return FileResponse(doc_path)

@app.get("/manual-rubros-pdf", response_class=FileResponse)
@app.get("/descargar-guia-pdf", response_class=FileResponse)
def serve_manual_rubros_pdf():
    pdf_path = os.path.join(os.path.dirname(__file__), "docs", "Manual_Comercial_Sofia_Rubros.pdf")
    return FileResponse(pdf_path, media_type="application/pdf", filename="Manual_Comercial_Sofia_Rubros.pdf")

# Monetization, Pricing Policy & Meta Cloud Costs
@app.get("/modelo-costos", response_class=FileResponse)
@app.get("/politica-precios", response_class=FileResponse)
def serve_modelo_costos_html():
    doc_path = os.path.join(os.path.dirname(__file__), "docs", "modelo_monetizacion_costos_meta.html")
    return FileResponse(doc_path)

@app.get("/descargar-costos-pdf", response_class=FileResponse)
@app.get("/modelo-costos-pdf", response_class=FileResponse)
def serve_modelo_costos_pdf():
    pdf_path = os.path.join(os.path.dirname(__file__), "docs", "Modelo_Monetizacion_Costos_Meta.pdf")
    return FileResponse(pdf_path, media_type="application/pdf", filename="Modelo_Monetizacion_Costos_Meta.pdf")

# Visual Catalog of Meta Templates (2 Pages A4)
@app.get("/catalogo-plantillas", response_class=FileResponse)
def serve_catalogo_plantillas_html():
    doc_path = os.path.join(os.path.dirname(__file__), "docs", "catalogo_visual_plantillas_meta_sofia.html")
    return FileResponse(doc_path)

@app.get("/descargar-catalogo-pdf", response_class=FileResponse)
@app.get("/catalogo-plantillas-pdf", response_class=FileResponse)
def serve_catalogo_plantillas_pdf():
    pdf_path = os.path.join(os.path.dirname(__file__), "docs", "Catalogo_Visual_Plantillas_Meta_Sofia.pdf")
    return FileResponse(pdf_path, media_type="application/pdf", filename="Catalogo_Visual_Plantillas_Meta_Sofia.pdf")

# Sales Playbook & Objections Manual (2 Pages A4)
@app.get("/manual-ventas", response_class=FileResponse)
def serve_manual_ventas_html():
    doc_path = os.path.join(os.path.dirname(__file__), "docs", "manual_ventas_y_objeciones_sofia.html")
    return FileResponse(doc_path)

@app.get("/descargar-manual-ventas-pdf", response_class=FileResponse)
@app.get("/manual-ventas-pdf", response_class=FileResponse)
def serve_manual_ventas_pdf():
    pdf_path = os.path.join(os.path.dirname(__file__), "docs", "MANUAL_VENTAS_Y_OBJECIONES_SOFIA.pdf")
    return FileResponse(pdf_path, media_type="application/pdf", filename="MANUAL_VENTAS_Y_OBJECIONES_SOFIA.pdf")

# Client-Facing Modo Jefe Guide & Pre-Delivery QA Checklist (2 Pages A4)
@app.get("/modo-jefe", response_class=FileResponse)
def serve_modo_jefe_html():
    doc_path = os.path.join(os.path.dirname(__file__), "docs", "manual_modo_jefe_cliente.html")
    return FileResponse(doc_path)

@app.get("/descargar-modo-jefe-pdf", response_class=FileResponse)
@app.get("/modo-jefe-pdf", response_class=FileResponse)
def serve_modo_jefe_pdf():
    pdf_path = os.path.join(os.path.dirname(__file__), "docs", "MANUAL_MODO_JEFE_CLIENTE.pdf")
    return FileResponse(pdf_path, media_type="application/pdf", filename="MANUAL_MODO_JEFE_CLIENTE.pdf")

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
app.include_router(bridge_router, prefix="/api/v1/bridge", tags=["Sofía Bridge"])
app.include_router(tenants_router)
app.include_router(tenants_router, prefix="/api/v1")
app.include_router(payments_router)

# Backward compatibility routes
app.include_router(webhook_router, prefix="/api/v1/prospecting", tags=["Prospecting Compatibility"])
app.include_router(outreach_router, prefix="/api/v1/prospecting", tags=["Prospecting Compatibility"])

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
