"""RSA keypair loading & generation for RS256 JWT signing.

Resolution order:
  1. Explicit PEM strings from the environment (prod: from a secret manager).
  2. PEM files in IDENTITY_JWT_KEY_DIR (generated once by the `ensure_jwt_keys`
     management command, which the container entrypoint runs before workers
     start — so all gunicorn workers share one key).
  3. (None, None) — the service can still boot (migrations, etc.); token
     issuance/verification will fail loudly if attempted without a key.

No `django.conf.settings` import here (settings imports this), keeping it pure.
"""

from __future__ import annotations

from pathlib import Path

PRIVATE_FILENAME = "jwt_private.pem"
PUBLIC_FILENAME = "jwt_public.pem"


def generate_keypair() -> tuple[str, str]:
    """Generate a fresh RSA-2048 keypair, returning (private_pem, public_pem)."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    public_pem = (
        private_key.public_key()
        .public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode()
    )
    return private_pem, public_pem


def _normalize_env_pem(value: str) -> str:
    # Allow PEM passed with escaped newlines (common in env injection).
    return value.replace("\\n", "\n").strip()


def ensure_key_files(key_dir: Path) -> tuple[str, str]:
    """Create the key files if missing; return their contents. Single-writer use."""
    key_dir.mkdir(parents=True, exist_ok=True)
    priv_path = key_dir / PRIVATE_FILENAME
    pub_path = key_dir / PUBLIC_FILENAME
    if not priv_path.exists() or not pub_path.exists():
        private_pem, public_pem = generate_keypair()
        priv_path.write_text(private_pem)
        pub_path.write_text(public_pem)
        try:
            priv_path.chmod(0o600)
        except OSError:
            pass
    return priv_path.read_text(), pub_path.read_text()


def load_keys(*, private_env: str, public_env: str, key_dir: Path) -> tuple[str | None, str | None]:
    """Resolve (private_pem, public_pem) for settings import time."""
    if private_env and public_env:
        return _normalize_env_pem(private_env), _normalize_env_pem(public_env)

    priv_path = key_dir / PRIVATE_FILENAME
    pub_path = key_dir / PUBLIC_FILENAME
    if priv_path.exists() and pub_path.exists():
        return priv_path.read_text(), pub_path.read_text()

    return None, None
