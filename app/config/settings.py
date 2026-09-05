from typing import Optional
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import field_validator

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Database
    DATABASE_URL: str = "sqlite:///./sofia.db"

    # Server / App URL
    APP_BASE_URL: str = "http://127.0.0.1:8000"
    SECRET_KEY: str = "sofia_ai_agency_default_secret_key"

    # AI Brain (Gemini Flash Lite Multimodal)
    GEMINI_API_KEY: Optional[str] = None

    # WhatsApp SDR Gateway (Whapi.cloud)
    WHATSAPP_AGENT_PHONE: Optional[str] = "5493435720312"
    WHATSAPP_ALERT_PHONE: Optional[str] = "5493434536447"
    WHATSAPP_API_URL: Optional[str] = "https://gate.whapi.cloud"
    WHATSAPP_API_TOKEN: Optional[str] = None

    # Mail / SMTP alerts
    MAIL_USERNAME: Optional[str] = None
    MAIL_PASSWORD: Optional[str] = None
    MAIL_FROM: Optional[str] = None
    MAIL_PORT: int = 587
    MAIL_SERVER: str = "smtp.gmail.com"
    MAIL_STARTTLS: bool = True
    MAIL_SSL_TLS: bool = False

    @field_validator("DATABASE_URL")
    @classmethod
    def clean_database_url(cls, v: str) -> str:
        """
        Cleans the database URL for modern SQLAlchemy and Render PostgreSQL compatibility.
        1. Replaces 'postgres://' with 'postgresql://'.
        2. Removes 'pgbouncer' query parameter if present.
        """
        if not v:
            return "sqlite:///./sofia.db"

        if v.startswith("postgres://"):
            v = v.replace("postgres://", "postgresql://", 1)

        try:
            parsed_url = urlparse(v)
            query_params = parse_qs(parsed_url.query)

            if "pgbouncer" in query_params:
                del query_params["pgbouncer"]
                new_query_string = urlencode(query_params, doseq=True)
                v = urlunparse((
                    parsed_url.scheme,
                    parsed_url.netloc,
                    parsed_url.path,
                    parsed_url.params,
                    new_query_string,
                    parsed_url.fragment
                ))
        except Exception:
            return v

        return v

settings = Settings()

def get_settings() -> Settings:
    return settings
