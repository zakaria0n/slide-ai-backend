"""Deck Doctor support tests: comment rate limiting (15-min cooldown)."""
from __future__ import annotations


def test_share_comment_rate_limited_15min(client) -> None:
    headers = _headers("42345678-1234-1234-1234-123456789012")

    # Create a deck + public share.
    created = client.post(
        "/api/v1/presentations/generate",
        json={"prompt": "Comment rate limit deck", "slide_count": 2},
        headers=headers,
    ).json()
    pid = created["id"]
    share = client.post(
        f"/api/v1/presentations/{pid}/shares",
        json={"visibility": "public"},
        headers=headers,
    ).json()
    token = share["token"]

    # First comment from this IP → OK.
    first = client.post(
        f"/api/v1/shared/{token}/comments",
        json={"author_name": "Reviewer", "content": "Nice deck!"},
    )
    assert first.status_code == 201, first.text

    # Second comment from the same IP within 15 minutes → 429.
    second = client.post(
        f"/api/v1/shared/{token}/comments",
        json={"content": "Spam attempt"},
    )
    assert second.status_code == 429, second.text
    body = second.json()
    detail = str(body.get("detail") or body.get("message") or "").lower()
    assert "wait" in detail and "minute" in detail, body


def _headers(uid: str) -> dict:
    from tests.test_generation_routes import _auth, _token

    return _auth(_token(uid))
