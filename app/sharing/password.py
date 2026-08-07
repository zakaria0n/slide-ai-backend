"""Password hashing helpers for share links."""
from __future__ import annotations

import hashlib
import secrets
from uuid import uuid4


def _generate_salt() -> str:
    """Generate a random 32-byte hex salt."""
    return secrets.token_hex(16)


def hash_password(password: str) -> str:
    """Hash a password using salted SHA-256.

    Returns ``salt:hash`` so the salt can be recovered for verification.
    """
    salt = _generate_salt()
    hashed = hashlib.sha256(f"{salt}{password}".encode("utf-8")).hexdigest()
    return f"{salt}:{hashed}"


def verify_password(password: str, password_hash: str) -> bool:
    """Verify a password against a stored ``salt:hash`` string."""
    try:
        salt, stored_hash = password_hash.split(":", 1)
    except ValueError:
        return False
    computed = hashlib.sha256(f"{salt}{password}".encode("utf-8")).hexdigest()
    return secrets.compare_digest(computed, stored_hash)


def generate_token() -> str:
    """Generate a random share token (UUID, matches the DB column type)."""
    return str(uuid4())
