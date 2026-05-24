import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()


def _bool(v: str | None, default: bool = False) -> bool:
    if v is None:
        return default
    return v.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    mock_mode: bool = _bool(os.getenv("MOCK_MODE"), default=True)

    vicidial_host: str = os.getenv("VICIDIAL_HOST", "")
    vicidial_port: int = int(os.getenv("VICIDIAL_PORT", "3306"))
    vicidial_user: str = os.getenv("VICIDIAL_USER", "")
    vicidial_password: str = os.getenv("VICIDIAL_PASSWORD", "")
    vicidial_db: str = os.getenv("VICIDIAL_DB", "asterisk")

    dispo_sale: str = os.getenv("DISPO_SALE", "SALE")
    dispo_callback: str = os.getenv("DISPO_CALLBACK", "CALLBK")

    supabase_url: str = os.getenv("SUPABASE_URL", "")
    supabase_service_key: str = os.getenv("SUPABASE_SERVICE_KEY", "")
    supabase_publishable_key: str = os.getenv("SUPABASE_PUBLISHABLE_KEY", "")

    anthropic_api_key: str = os.getenv("ANTHROPIC_API_KEY", "")

    allowed_origin: str = os.getenv("ALLOWED_ORIGIN", "*")

    api_token: str = os.getenv("API_TOKEN", "")

    redis_url: str = os.getenv("REDIS_URL", "")
    # TTL in seconds for cached endpoint responses (safety net; prefetch keeps cache warm)
    cache_ttl: int = int(os.getenv("CACHE_TTL", "300"))


settings = Settings()
