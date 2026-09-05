import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(BASE_DIR)
if PARENT_DIR not in sys.path:
    sys.path.insert(0, PARENT_DIR)

import json
import csv
import asyncio
from io import StringIO, BytesIO
from fastapi import FastAPI, Query, HTTPException, Response
from fastapi.responses import StreamingResponse, HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from prospector.scraper import prospect_leads_generator

app = FastAPI(title="Air Control PRO — Prospectador de Alojamientos (Local)")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")
TEMPLATES_FILE = os.path.join(BASE_DIR, "pitch_templates.json")

os.makedirs(STATIC_DIR, exist_ok=True)

class TemplateModel(BaseModel):
    id: str
    nombre: str
    canal: str
    asunto: str
    cuerpo: str

def load_templates():
    if os.path.exists(TEMPLATES_FILE):
        with open(TEMPLATES_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []

def save_templates(data):
    with open(TEMPLATES_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

@app.get("/")
def get_dashboard():
    index_path = os.path.join(STATIC_DIR, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return HTMLResponse("<h1>Air Control PRO - Prospectador Local</h1><p>index.html no encontrado.</p>")

@app.get("/dossier-propietario")
def get_dossier_propietario():
    dossier_path = os.path.join(PARENT_DIR, "PROPIETARIO_ARGENTINA.html")
    if os.path.exists(dossier_path):
        return FileResponse(dossier_path)
    return HTMLResponse("<h1>Dossier Propietario no encontrado</h1>")

@app.get("/dossier-partner-nacional")
def get_dossier_partner_nacional():
    dossier_path = os.path.join(PARENT_DIR, "DOSSIER_PARTNER_NACIONAL.html")
    if os.path.exists(dossier_path):
        return FileResponse(dossier_path)
    return HTMLResponse("<h1>Dossier Partner Nacional no encontrado</h1>")

@app.get("/flayer-story-pro")
def get_flayer_story_pro():
    flyer_path = os.path.join(PARENT_DIR, "FLYER_STORY_PRO.html")
    if os.path.exists(flyer_path):
        return FileResponse(flyer_path)
    return HTMLResponse("<h1>Flayer Story PRO no encontrado</h1>")

@app.get("/dossier-hotelero-financiado")
def get_dossier_hotelero_financiado():
    dossier_path = os.path.join(PARENT_DIR, "DOSSIER_HOTELERO_FINANCIADO.html")
    if os.path.exists(dossier_path):
        return FileResponse(dossier_path)
    return HTMLResponse("<h1>Dossier Hotelero Financiado no encontrado</h1>")

@app.get("/dossier-inversor-privado")
def get_dossier_inversor_privado():
    dossier_path = os.path.join(PARENT_DIR, "DOSSIER_INVERSOR_PRIVADO.html")
    if os.path.exists(dossier_path):
        return FileResponse(dossier_path)
    return HTMLResponse("<h1>Dossier Inversor Privado no encontrado</h1>")

@app.get("/dossier-inversor")
def get_dossier_inversor():
    dossier_path = os.path.join(PARENT_DIR, "DOSSIER_POOL_INVERSORES.html")
    if os.path.exists(dossier_path):
        return FileResponse(dossier_path)
    return HTMLResponse("<h1>Dossier Inversor no encontrado</h1>")

@app.get("/solicitud-reserva-financiada")
def get_solicitud_reserva():
    doc_path = os.path.join(PARENT_DIR, "SOLICITUD_EQUIPAMIENTO_FINANCIADO.html")
    if os.path.exists(doc_path):
        return FileResponse(doc_path)
    return HTMLResponse("<h1>Solicitud no encontrada</h1>")

@app.get("/contrato-inversor-privado")
def get_contrato_inversor():
    doc_path = os.path.join(PARENT_DIR, "CONTRATO_INVERSOR_PRIVADO.html")
    if os.path.exists(doc_path):
        return FileResponse(doc_path)
    return HTMLResponse("<h1>Contrato Inversor no encontrado</h1>")

@app.get("/api/templates")
def get_all_templates():
    return load_templates()

@app.post("/api/templates")
def update_template(tpl: TemplateModel):
    templates = load_templates()
    found = False
    for idx, t in enumerate(templates):
        if t["id"] == tpl.id:
            templates[idx] = tpl.model_dump()
            found = True
            break
    if not found:
        templates.append(tpl.model_dump())
    save_templates(templates)
    return {"status": "ok", "template": tpl}

@app.get("/api/prospect/stream")
def prospect_stream(rubro: str = Query("Hoteles"), ciudad: str = Query("Paraná")):
    """
    Server-Sent Events endpoint to stream scraping progress and leads.
    """
    async def event_generator():
        generator = prospect_leads_generator(rubro, ciudad)
        for event in generator:
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
            await asyncio.sleep(0.05)

    return StreamingResponse(event_generator(), media_type="text/event-stream")

if __name__ == "__main__":
    import uvicorn
    print("🚀 Servidor del Prospectador iniciado en http://localhost:8500")
    uvicorn.run("prospector.main:app", host="127.0.0.1", port=8500, reload=True)
