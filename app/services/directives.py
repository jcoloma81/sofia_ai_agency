import os
import re
import json
import logging
from typing import Dict, Any, List, Optional
import httpx
from app.config.settings import settings

logger = logging.getLogger(__name__)

DIRECTIVES_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "commercial_directives.json")

DEFAULT_DIRECTIVES = {
    "min_order_amount": 50000,
    "cutoff_time": "21:00 hs",
    "coverage_zones": "Centro y zonas asignadas",
    "custom_rules": [
        "Monto mínimo para flete gratis: $50.000 (si un cliente no llega, le sugiero productos de alta rotación para completar el ticket).",
        "Corte de pedidos para el reparto de mañana: Hasta las 21:00 hs.",
        "Zona de cobertura: Centro y zonas asignadas."
    ],
    "raw_summary": "• *Monto mínimo para flete gratis:* $50.000 (si un cliente no llega, le sugiero productos de alta rotación para completar el ticket).\n• *Corte de pedidos para el reparto de mañana:* Hasta las 21:00 hs.\n• *Zona de cobertura:* Centro y zonas asignadas."
}

class DirectivesService:
    def __init__(self, storage_path: str = DIRECTIVES_FILE):
        self.storage_path = storage_path
        self.data = self._load()

    def _load(self) -> Dict[str, Any]:
        if os.path.exists(self.storage_path):
            try:
                with open(self.storage_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, dict) and "custom_rules" in data:
                        return data
            except Exception as e:
                logger.warning(f"Error loading directives from {self.storage_path}: {e}")
        return dict(DEFAULT_DIRECTIVES)

    def _save(self):
        try:
            os.makedirs(os.path.dirname(self.storage_path), exist_ok=True)
            with open(self.storage_path, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Error saving directives to {self.storage_path}: {e}")

    def get_prompt_context(self) -> str:
        """Returns structured instructions for Gemini to follow during sales chats."""
        rules = self.data.get("custom_rules", [])
        if not rules:
            return ""
        lines = ["DIRECTIVAS COMERCIALES VIGENTES DE LA DISTRIBUIDORA (SEGUIR ESTRICTAMENTE):"]
        for r in rules:
            lines.append(f"- {r}")
        return "\n".join(lines)

    async def update_from_boss_message(self, boss_text: str) -> str:
        """
        Parses instructions sent by the business owner (by text or voice),
        extracts the updated rules, persists them, and returns an executive confirmation message.
        """
        gemini_key = settings.GEMINI_API_KEY
        updated_rules: Optional[List[str]] = None

        if gemini_key:
            prompt = (
                f"El dueño de la distribuidora envió esta indicación o directiva comercial por WhatsApp:\n"
                f"\"{boss_text}\"\n\n"
                f"Directivas previas:\n{json.dumps(self.data.get('custom_rules', []), ensure_ascii=False)}\n\n"
                f"Tarea:\n"
                f"Extraé las directivas comerciales y operativas en una lista de reglas claras en español.\n"
                f"Devolvé ÚNICAMENTE un array JSON válido de strings con las reglas. Sin texto extra. Ejemplo: [\"Monto mínimo para flete gratis: $50.000\", \"Zona de cobertura: Centro\"]"
            )
            payload = {
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {"temperature": 0.1, "maxOutputTokens": 300}
            }
            models = ["gemini-flash-lite-latest", "gemini-3.5-flash-lite", "gemini-3.6-flash"]
            for m in models:
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent?key={gemini_key}"
                try:
                    async with httpx.AsyncClient(timeout=4.0) as client:
                        res = await client.post(url, json=payload)
                        if res.status_code == 200:
                            data = res.json()
                            candidates = data.get("candidates", [])
                            if candidates and "content" in candidates[0]:
                                raw_json = candidates[0]["content"]["parts"][0]["text"].strip()
                                raw_json = re.sub(r'^```(?:json)?\s*', '', raw_json)
                                raw_json = re.sub(r'\s*```$', '', raw_json).strip()
                                parsed = json.loads(raw_json)
                                if isinstance(parsed, list) and len(parsed) > 0:
                                    updated_rules = [str(x).strip() for x in parsed]
                                    break
                except Exception as err:
                    logger.warning(f"Error extracting directives with {m}: {err}")

        # Deterministic fallback if Gemini is offline or slow
        if not updated_rules:
            updated_rules = []
            text_lower = boss_text.lower()
            
            # Detect minimum amount
            amounts = re.findall(r'\d+', text_lower.replace('.', ''))
            valid_amount = next((a for a in amounts if int(a) >= 1000), None)
            if valid_amount:
                formatted_amt = f"${int(valid_amount):,}".replace(",", ".")
                updated_rules.append(f"Monto mínimo para flete gratis: {formatted_amt} (si un cliente no llega, le sugiero productos de alta rotación para completar el ticket).")
            elif "minimo" in text_lower or "mínimo" in text_lower or "cupo" in text_lower:
                updated_rules.append("Monto mínimo para flete gratis: $50.000 (si un cliente no llega, le sugiero productos de alta rotación para completar el ticket).")

            # Detect cutoff hours
            hour_match = re.search(r'(\d{1,2})\s*(?:hs|horas|:\d{2})', text_lower)
            if hour_match:
                updated_rules.append(f"Corte de pedidos para el reparto de mañana: Hasta las {hour_match.group(1)}:00 hs.")
            else:
                updated_rules.append("Corte de pedidos para el reparto de mañana: Hasta las 21:00 hs.")

            # Detect zones
            if "centro" in text_lower:
                updated_rules.append("Zona de cobertura: Centro y zonas asignadas.")
            elif "zona" in text_lower:
                updated_rules.append("Zona de cobertura: Zonas asignadas de reparto.")
            else:
                updated_rules.append("Zona de cobertura: Centro y zonas asignadas.")

        self.data["custom_rules"] = updated_rules
        bullets = "\n".join(f"• *{r.split(':')[0]}:*{':'.join(r.split(':')[1:])}" if ":" in r else f"• {r}" for r in updated_rules)
        self.data["raw_summary"] = bullets
        self._save()

        reply = (
            "✅ *¡Directiva comercial configurada con éxito!*\n\n"
            "Entendido Javier. A partir de ahora aplico las siguientes reglas para todos los clientes:\n"
            f"{bullets}\n\n"
            "💡 Ya tengo estas directivas activas para todas las cotizaciones y pedidos."
        )
        return reply

directives_service = DirectivesService()
