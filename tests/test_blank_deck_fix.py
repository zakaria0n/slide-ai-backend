"""Regression: blank-deck flow — PUT spec on a specless deck must succeed."""
from __future__ import annotations


def _headers(uid: str) -> dict:
    from tests.test_generation_routes import _auth, _token

    return _auth(_token(uid))


def test_blank_deck_put_spec_on_specless_deck(client) -> None:
    headers = _headers("61345678-1234-1234-1234-123456789012")

    # Create a draft WITHOUT a spec (what POST /presentations does).
    created = client.post(
        "/api/v1/presentations",
        json={"title": "Blank deck"},
        headers=headers,
    ).json()
    pid = created["id"]

    # The deck has no spec yet — GET must 404 (pre-seed state).
    before = client.get(f"/api/v1/presentations/{pid}/spec", headers=headers)
    assert before.status_code == 404

    # PUT defines the FIRST spec — must NOT 500.
    blank_spec = {
        "meta": {
            "title": "Blank deck",
            "theme": None,
            "background": None,
            "language": "English",
            "tone": "Professional",
        },
        "slides": [{"layout": "blank", "elements": []}],
    }
    put = client.put(f"/api/v1/presentations/{pid}/spec", json=blank_spec, headers=headers)
    assert put.status_code == 200, put.text
    assert put.headers.get("X-Updated-At")

    # GET now returns the spec.
    got = client.get(f"/api/v1/presentations/{pid}/spec", headers=headers)
    assert got.status_code == 200
    assert got.json()["slides"][0]["layout"] == "blank"
