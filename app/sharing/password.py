"""Password hashing helpers for share links."""
from __future__ import annotations

import hashlib
import secrets


def hash_password(password: str) -> str:
    """Hash a password using SHA-256."""
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def verify_password(password: str, password_hash: str) -> bool:
    """Verify a password against a stored hash."""
    return hash_password(password) == password_hash


def generate_token() -> str:
    """Generate a random share token."""
    return secrets.token_urlsafe(24)
