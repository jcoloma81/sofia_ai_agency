import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(BASE_DIR)
if PARENT_DIR not in sys.path:
    sys.path.insert(0, PARENT_DIR)

import json
import asyncio
from fastapi import FastAPI, Query
from fastapi.responses import StreamingResponse, HTMLResponse, FileResponse
from pydantic import BaseModel
from prospector.scraper import prospect_leads_generator

app = FastAPI(title="Sofía AI Agency — Prospectador de Leads B2B (Local)")

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
    return HTMLResponse("<h1>Sofía AI Agency - Prospectador Local</h1><p>index.html no encontrado.</p>")

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
def prospect_stream(rubro: str = Query("Distribuidoras"), ciudad: str = Query("Paraná")):
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
