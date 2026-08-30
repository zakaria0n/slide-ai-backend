"""Slide library endpoints — save, list, insert-copy, delete."""
from __future__ import annotations


def _headers(uid: str) -> dict:
    from tests.test_generation_routes import _auth, _token

    return _auth(_token(uid))


def test_slide_library_save_list_delete(client) -> None:
    headers = _headers("32345678-1234-1234-1234-123456789012")

    slide = {
        "layout": "title",
        "elements": [{"type": "title", "text": "Reusable Title", "level": 1}],
    }

    # Save
    saved = client.post(
        "/api/v1/slide-library",
        json={"title": "Reusable Title", "slide": slide},
        headers=headers,
    )
    assert saved.status_code == 201, saved.text
    body = saved.json()
    assert body["title"] == "Reusable Title"
    assert body["slide"]["elements"][0]["text"] == "Reusable Title"

    # List
    listed = client.get("/api/v1/slide-library", headers=headers)
    assert listed.status_code == 200
    items = listed.json()["slides"]
    assert any(s["id"] == body["id"] for s in items)

    # Delete
    deleted = client.delete(f"/api/v1/slide-library/{body['id']}", headers=headers)
    assert deleted.status_code == 204
    after = client.get("/api/v1/slide-library", headers=headers)
    assert all(s["id"] != body["id"] for s in after.json()["slides"])


def test_slide_library_requires_auth(client) -> None:
    assert client.get("/api/v1/slide-library").status_code == 401


def test_slide_library_isolated_per_user(client) -> None:
    headers_a = _headers("32345678-1234-1234-1234-123456789012")
    headers_b = _headers("42345678-1234-1234-1234-123456789012")

    saved = client.post(
        "/api/v1/slide-library",
        json={"title": "A's slide", "slide": {"layout": "blank", "elements": []}},
        headers=headers_a,
    )
    assert saved.status_code == 201
    slide_id = saved.json()["id"]

    # User B cannot see or delete user A's library slide.
    listed_b = client.get("/api/v1/slide-library", headers=headers_b).json()
    assert all(s["id"] != slide_id for s in listed_b["slides"])
    deleted_b = client.delete(f"/api/v1/slide-library/{slide_id}", headers=headers_b)
    assert deleted_b.status_code == 404
