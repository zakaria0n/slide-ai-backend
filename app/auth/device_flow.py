"""Device-flow pairing store (in-memory, single process).

A CLI asks /auth/device/start, the user approves the shown code in the
browser, and /auth/device/poll hands the CLI a long-lived token.
Entries expire after 15 minutes.
"""
from __future__ import annotations

import secrets
import string
import time
from typing import Any

_TTL_SECONDS = 900
_PENDING: dict[str, dict[str, Any]] = {}

_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no I/1/O/0 look-alikes


def _new_user_code() -> str:
    rng = secrets.SystemRandom()
    chars = [rng.choice(_ALPHABET) for _ in range(8)]
    return "-".join(["".join(chars[:4]), "".join(chars[4:])])


def _prune() -> None:
    now = time.monotonic()
    for code in [k for k, v in _PENDING.items() if now - v["created"] > _TTL_SECONDS]:
        _PENDING.pop(code, None)


def start_pairing() -> dict[str, Any]:
    _prune()
    user_code = _new_user_code()
    device_code = secrets.token_urlsafe(24)
    _PENDING[device_code] = {
        "user_code": user_code,
        "status": "pending",
        "created": time.monotonic(),
    }
    return {
        "device_code": device_code,
        "user_code": user_code,
        "expires_in": _TTL_SECONDS,
    }


def approve(user_code: str, *, user_id, email: str, access_token: str) -> None:
    """Approve a pending pairing by its user code (minted token attached)."""
    _prune()
    for entry in _PENDING.values():
        if entry["user_code"] == user_code.upper() and entry["status"] == "pending":
            entry.update(status="approved", user_id=str(user_id), email=email, access_token=access_token)
            return
    raise KeyError(user_code)


def poll(device_code: str, jwt_secret: str) -> dict[str, Any] | None:
    """Return the pairing state; hands over the token once approved."""
    import jwt as _jwt

    _prune()
    entry = _PENDING.get(device_code)
    if entry is None:
        return None
    if entry["status"] == "pending":
        return {"status": "pending"}
    # Approved: verify the minted token is still valid, then return it.
    try:
        claims = _jwt.decode(entry["access_token"], jwt_secret, algorithms=["HS256"], audience="authenticated")
    except Exception:
        return {"status": "expired"}
    return {
        "status": "approved",
        "access_token": entry["access_token"],
        "token_type": "bearer",
        "expires_in": int(claims.get("exp", 0)) - int(time.time()),
        "user": {"id": claims.get("sub"), "email": claims.get("email")},
    }
