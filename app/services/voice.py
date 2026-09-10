import io
import re
import logging
from typing import Optional
import edge_tts

logger = logging.getLogger(__name__)

DEFAULT_VOICE = "es-AR-ElenaNeural"

def clean_text_for_speech(text: str) -> str:
    """
    Cleans markdown formatting, emojis, bullets and URLs so the TTS engine speaks naturally.
    """
    if not text:
        return ""
    # Remove URLs
    cleaned = re.sub(r'https?://\S+|www\.\S+', '', text)
    # Remove bullets, asterisks, brackets
    cleaned = re.sub(r'[\*\_#•\-~`]', ' ', cleaned)
    # Normalize excessive punctuation or whitespace
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    return cleaned

async def text_to_speech_bytes(text: str, voice: str = DEFAULT_VOICE) -> bytes:
    """
    Converts text to MP3 audio bytes using Edge TTS neural voice.
    """
    cleaned = clean_text_for_speech(text)
    if not cleaned:
        return b""
    try:
        communicate = edge_tts.Communicate(cleaned, voice)
        audio_buffer = io.BytesIO()
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                audio_buffer.write(chunk["data"])
        return audio_buffer.getvalue()
    except Exception as e:
        logger.error(f"Error generating speech bytes: {e}")
        return b""
