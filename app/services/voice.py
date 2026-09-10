import io
import re
import os
import tempfile
import asyncio
import logging
from typing import Optional
import httpx
import edge_tts
from app.config.settings import settings

logger = logging.getLogger(__name__)

DEFAULT_EDGE_VOICE = "es-AR-ElenaNeural"

def clean_text_for_speech(text: str) -> str:
    if not text:
        return ""
    # Remove URLs
    cleaned = re.sub(r'https?://\S+|www\.\S+', '', text)
    # Remove bullets, asterisks, brackets, hashes
    cleaned = re.sub(r'[\*\_#•\-~`]', ' ', cleaned)
    # Normalize whitespace
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    return cleaned

async def convert_to_ogg_opus(input_bytes: bytes) -> bytes:
    """
    Converts MP3 or raw audio bytes to native WhatsApp voice note OGG Opus format
    using ffmpeg (48kHz, mono, libopus).
    """
    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as in_file:
        in_file.write(input_bytes)
        in_path = in_file.name

    out_path = in_path.replace(".mp3", ".ogg")
    try:
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-y", "-i", in_path,
            "-c:a", "libopus", "-b:a", "32k", "-ac", "1", "-ar", "48000",
            out_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        await proc.communicate()
        if os.path.exists(out_path):
            with open(out_path, "rb") as f:
                return f.read()
    except Exception as e:
        logger.error(f"Error converting audio to OGG Opus with ffmpeg: {e}")
    finally:
        if os.path.exists(in_path):
            os.remove(in_path)
        if os.path.exists(out_path):
            os.remove(out_path)
    return input_bytes

async def text_to_speech_bytes(text: str, voice_id: Optional[str] = None) -> bytes:
    """
    Converts text to native WhatsApp voice note bytes (OGG Opus).
    Prioritizes ElevenLabs for human-level conversational fluidity,
    falling back to Edge-TTS.
    """
    cleaned = clean_text_for_speech(text)
    if not cleaned:
        return b""

    # 1. Try ElevenLabs Ultra-Realistic Conversational Voice
    if settings.ELEVENLABS_API_KEY:
        target_voice = voice_id or settings.ELEVENLABS_VOICE_ID or "cgSgspJ2msm6clMCkdW9"
        url = f"https://api.elevenlabs.io/v1/text-to-speech/{target_voice}"
        headers = {
            "xi-api-key": settings.ELEVENLABS_API_KEY,
            "Content-Type": "application/json"
        }
        payload = {
            "text": cleaned,
            "model_id": "eleven_multilingual_v2",
            "voice_settings": {
                "stability": 0.45,
                "similarity_boost": 0.8
            }
        }
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                res = await client.post(url, headers=headers, json=payload)
                if res.status_code == 200 and len(res.content) > 0:
                    logger.info(f"✨ ElevenLabs generated {len(res.content)} bytes of speech")
                    # Convert to OGG Opus for native WhatsApp voice note
                    return await convert_to_ogg_opus(res.content)
                else:
                    logger.warning(f"ElevenLabs error ({res.status_code}): {res.text}, falling back to Edge-TTS")
        except Exception as e:
            logger.error(f"ElevenLabs request failed: {e}")

    # 2. Fallback to Edge-TTS
    try:
        communicate = edge_tts.Communicate(cleaned, DEFAULT_EDGE_VOICE)
        audio_buffer = io.BytesIO()
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                audio_buffer.write(chunk["data"])
        raw_mp3 = audio_buffer.getvalue()
        if raw_mp3:
            return await convert_to_ogg_opus(raw_mp3)
    except Exception as e:
        logger.error(f"Edge-TTS failed: {e}")

    return b""
