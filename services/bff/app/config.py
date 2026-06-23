"""BFF configuration from the environment (twelve-factor)."""

from __future__ import annotations

import os


class Settings:
    identity_base_url: str = os.getenv("BFF_IDENTITY_BASE_URL", "http://identity:8000")
    jwks_url: str = os.getenv("BFF_JWKS_URL", "http://identity:8000/.well-known/jwks.json")
    jwt_issuer: str = os.getenv("JWT_ISSUER", "tara-identity")
    jwt_audience: str = os.getenv("JWT_AUDIENCE", "tara")
    jwks_cache_ttl: int = int(os.getenv("BFF_JWKS_CACHE_TTL", "300"))
    allowed_origins: list[str] = [
        o.strip()
        for o in os.getenv("BFF_ALLOWED_ORIGINS", "http://localhost:5173").split(",")
        if o.strip()
    ]
    upstream_timeout_seconds: float = float(os.getenv("BFF_UPSTREAM_TIMEOUT", "3.0"))


settings = Settings()
