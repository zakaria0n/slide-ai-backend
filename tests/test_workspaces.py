"""Tests for workspaces using FakeAsyncClient."""
from __future__ import annotations

import jwt
import pytest
from fastapi.testclient import TestClient

SECRET = "test-secret"


def _token(user_id: str, secret: str = SECRET, email: str = "u@example.com") -> str:
    return jwt.encode({"sub": user_id, "email": email, "aud": "authenticated"}, secret, algorithm="HS256")


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_create_and_list_workspace(client: TestClient) -> None:
    uid = "11111111-1111-1111-1111-111111111111"
    headers = _auth(_token(uid))

    res = client.post("/api/v1/workspaces", json={"name": "My Team"}, headers=headers)
    assert res.status_code == 201
    ws = res.json()
    assert ws["name"] == "My Team"

    listing = client.get("/api/v1/workspaces", headers=headers)
    assert listing.status_code == 200
    assert len(listing.json()["workspaces"]) == 1


def test_invite_and_accept_member(client: TestClient) -> None:
    owner = "22222222-2222-2222-2222-222222222222"
    member_uid = "33333333-3333-3333-3333-333333333333"
    member_email = "editor@example.com"
    headers = _auth(_token(owner))
    member_headers = _auth(_token(member_uid, email=member_email))

    ws = client.post("/api/v1/workspaces", json={"name": "WS"}, headers=headers).json()
    wid = ws["id"]

    # Invite by email.
    res = client.post(
        f"/api/v1/workspaces/{wid}/invitations",
        json={"email": member_email, "role": "editor"},
        headers=headers,
    )
    assert res.status_code == 201
    assert res.json()["status"] == "pending"
    inv_id = res.json()["id"]

    # The invited user sees it in their pending list.
    pending = client.get("/api/v1/workspaces/invitations/pending", headers=member_headers)
    assert pending.status_code == 200
    invites = pending.json()["invitations"]
    assert len(invites) == 1
    assert invites[0]["workspace_name"] == "WS"

    # Accept -> becomes a member.
    acc = client.post(f"/api/v1/workspaces/invitations/{inv_id}/accept", headers=member_headers)
    assert acc.status_code == 200
    assert acc.json()["role"] == "editor"

    members = client.get(f"/api/v1/workspaces/{wid}/members", headers=headers)
    assert len(members.json()["members"]) == 2  # owner + editor

    # The member can now see the workspace in their own list.
    listing = client.get("/api/v1/workspaces", headers=member_headers)
    assert len(listing.json()["workspaces"]) == 1


def test_decline_invitation(client: TestClient) -> None:
    owner = "44440000-4444-4444-4444-444444444444"
    member_uid = "55550000-5555-5555-5555-555555555555"
    member_email = "decliner@example.com"
    headers = _auth(_token(owner))
    member_headers = _auth(_token(member_uid, email=member_email))

    ws = client.post("/api/v1/workspaces", json={"name": "WS"}, headers=headers).json()
    wid = ws["id"]

    res = client.post(
        f"/api/v1/workspaces/{wid}/invitations",
        json={"email": member_email, "role": "viewer"},
        headers=headers,
    )
    inv_id = res.json()["id"]

    dec = client.post(f"/api/v1/workspaces/invitations/{inv_id}/decline", headers=member_headers)
    assert dec.status_code == 204

    # Cannot accept after declining.
    acc = client.post(f"/api/v1/workspaces/invitations/{inv_id}/accept", headers=member_headers)
    assert acc.status_code == 409

    members = client.get(f"/api/v1/workspaces/{wid}/members", headers=headers)
    assert len(members.json()["members"]) == 1


def test_invitation_requires_owner(client: TestClient) -> None:
    owner = "66660000-6666-6666-6666-666666666666"
    stranger = "77770000-7777-7777-7777-777777777777"
    headers_owner = _auth(_token(owner))
    headers_stranger = _auth(_token(stranger))

    ws = client.post("/api/v1/workspaces", json={"name": "WS"}, headers=headers_owner).json()
    wid = ws["id"]

    res = client.post(
        f"/api/v1/workspaces/{wid}/invitations",
        json={"email": "someone@example.com", "role": "viewer"},
        headers=headers_stranger,
    )
    assert res.status_code == 404


def test_cancel_invitation(client: TestClient) -> None:
    owner = "88880000-8888-8888-8888-888888888888"
    member_email = "cancelled@example.com"
    headers = _auth(_token(owner))

    ws = client.post("/api/v1/workspaces", json={"name": "WS"}, headers=headers).json()
    wid = ws["id"]

    res = client.post(
        f"/api/v1/workspaces/{wid}/invitations",
        json={"email": member_email, "role": "viewer"},
        headers=headers,
    )
    inv_id = res.json()["id"]

    cancel = client.delete(f"/api/v1/workspaces/{wid}/invitations/{inv_id}", headers=headers)
    assert cancel.status_code == 204

    invites = client.get(f"/api/v1/workspaces/{wid}/invitations", headers=headers)
    assert invites.json()["invitations"][0]["status"] == "cancelled"


def test_change_role(client: TestClient) -> None:
    owner = "44444444-4444-4444-4444-444444444444"
    member_uid = "55555555-5555-5555-5555-555555555555"
    member_email = "viewer@example.com"
    headers = _auth(_token(owner))
    member_headers = _auth(_token(member_uid, email=member_email))

    ws = client.post("/api/v1/workspaces", json={"name": "WS"}, headers=headers).json()
    wid = ws["id"]
    inv = client.post(
        f"/api/v1/workspaces/{wid}/invitations",
        json={"email": member_email, "role": "viewer"},
        headers=headers,
    ).json()
    client.post(f"/api/v1/workspaces/invitations/{inv['id']}/accept", headers=member_headers)

    res = client.patch(
        f"/api/v1/workspaces/{wid}/members/{member_uid}",
        json={"role": "admin"},
        headers=headers,
    )
    assert res.status_code == 200
    assert res.json()["role"] == "admin"


def test_remove_member(client: TestClient) -> None:
    owner = "66666666-6666-6666-6666-666666666666"
    member_uid = "77777777-7777-7777-7777-777777777777"
    member_email = "removee@example.com"
    headers = _auth(_token(owner))
    member_headers = _auth(_token(member_uid, email=member_email))

    ws = client.post("/api/v1/workspaces", json={"name": "WS"}, headers=headers).json()
    wid = ws["id"]
    inv = client.post(
        f"/api/v1/workspaces/{wid}/invitations",
        json={"email": member_email, "role": "viewer"},
        headers=headers,
    ).json()
    client.post(f"/api/v1/workspaces/invitations/{inv['id']}/accept", headers=member_headers)

    res = client.delete(f"/api/v1/workspaces/{wid}/members/{member_uid}", headers=headers)
    assert res.status_code == 204

    members = client.get(f"/api/v1/workspaces/{wid}/members", headers=headers)
    assert len(members.json()["members"]) == 1  # only owner


def test_leave_workspace(client: TestClient) -> None:
    owner = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    member_uid = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    member_email = "leaver@example.com"
    headers = _auth(_token(owner))
    member_headers = _auth(_token(member_uid, email=member_email))

    ws = client.post("/api/v1/workspaces", json={"name": "WS"}, headers=headers).json()
    wid = ws["id"]
    inv = client.post(
        f"/api/v1/workspaces/{wid}/invitations",
        json={"email": member_email, "role": "viewer"},
        headers=headers,
    ).json()
    client.post(f"/api/v1/workspaces/invitations/{inv['id']}/accept", headers=member_headers)

    res = client.post(f"/api/v1/workspaces/{wid}/leave", headers=member_headers)
    assert res.status_code == 204

    members = client.get(f"/api/v1/workspaces/{wid}/members", headers=headers)
    assert len(members.json()["members"]) == 1  # only owner remains

    listing = client.get("/api/v1/workspaces", headers=member_headers)
    assert listing.json()["workspaces"] == []  # leaver no longer sees it


def test_owner_cannot_leave(client: TestClient) -> None:
    owner = "cccccccc-cccc-cccc-cccc-cccccccccccc"
    headers = _auth(_token(owner))

    ws = client.post("/api/v1/workspaces", json={"name": "WS"}, headers=headers).json()
    wid = ws["id"]

    res = client.post(f"/api/v1/workspaces/{wid}/leave", headers=headers)
    assert res.status_code == 403


def test_audit_log(client: TestClient) -> None:
    owner = "88888888-8888-8888-8888-888888888888"
    member_uid = "99999999-9999-9999-9999-999999999999"
    member_email = "audit@example.com"
    headers = _auth(_token(owner))
    member_headers = _auth(_token(member_uid, email=member_email))

    ws = client.post("/api/v1/workspaces", json={"name": "WS"}, headers=headers).json()
    wid = ws["id"]
    client.post(
        f"/api/v1/workspaces/{wid}/invitations",
        json={"email": member_email, "role": "editor"},
        headers=headers,
    )

    audit = client.get(f"/api/v1/workspaces/{wid}/audit", headers=headers)
    assert audit.status_code == 200
    entries = audit.json()["entries"]
    assert len(entries) >= 1
    assert entries[0]["action"] == "invite_member"


def test_delete_workspace_owner(client: TestClient) -> None:
    owner = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    headers = _auth(_token(owner))

    ws = client.post("/api/v1/workspaces", json={"name": "To Delete"}, headers=headers).json()
    wid = ws["id"]

    res = client.delete(f"/api/v1/workspaces/{wid}", headers=headers)
    assert res.status_code == 204

    listing = client.get("/api/v1/workspaces", headers=headers)
    assert listing.json()["workspaces"] == []


def test_delete_workspace_requires_owner(client: TestClient) -> None:
    owner = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    other = "cccccccc-cccc-cccc-cccc-cccccccccccc"
    headers_owner = _auth(_token(owner))
    headers_other = _auth(_token(other))

    ws = client.post("/api/v1/workspaces", json={"name": "WS"}, headers=headers_owner).json()
    wid = ws["id"]

    res = client.delete(f"/api/v1/workspaces/{wid}", headers=headers_other)
    assert res.status_code == 404

    listing = client.get("/api/v1/workspaces", headers=headers_owner)
    assert len(listing.json()["workspaces"]) == 1


def test_delete_workspace_missing(client: TestClient) -> None:
    owner = "dddddddd-dddd-dddd-dddd-dddddddddddd"
    headers = _auth(_token(owner))

    res = client.delete(
        "/api/v1/workspaces/eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee", headers=headers
    )
    assert res.status_code == 404


def test_search_users(client: TestClient) -> None:
    owner = "eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee"
    headers = _auth(_token(owner))

    res = client.get("/api/v1/workspaces/search/users?q=foo", headers=headers)
    assert res.status_code == 200
    assert res.json()["users"] == []

    empty = client.get("/api/v1/workspaces/search/users", headers=headers)
    assert empty.status_code == 200
    assert empty.json()["users"] == []


def test_workspace_presentations(client: TestClient) -> None:
    owner = "aaaaaaaa-0000-0000-0000-aaaaaaaaaaaa"
    headers = _auth(_token(owner))

    ws = client.post("/api/v1/workspaces", json={"name": "WS"}, headers=headers).json()
    wid = ws["id"]
    pid = "bbbbbbbb-1111-1111-1111-bbbbbbbbbbbb"

    # Empty by default.
    listing = client.get(f"/api/v1/workspaces/{wid}/presentations", headers=headers)
    assert listing.status_code == 200
    assert listing.json()["presentation_ids"] == []

    # Add.
    res = client.post(
        f"/api/v1/workspaces/{wid}/presentations",
        json={"presentation_id": pid},
        headers=headers,
    )
    assert res.status_code == 201

    listing = client.get(f"/api/v1/workspaces/{wid}/presentations", headers=headers)
    assert listing.json()["presentation_ids"] == [pid]

    # Remove.
    rem = client.delete(f"/api/v1/workspaces/{wid}/presentations/{pid}", headers=headers)
    assert rem.status_code == 204

    listing = client.get(f"/api/v1/workspaces/{wid}/presentations", headers=headers)
    assert listing.json()["presentation_ids"] == []


def test_member_can_access_workspace_presentation(client: TestClient) -> None:
    owner = "aaaa1111-0000-0000-0000-aaaa11110000"
    member = "bbbb2222-0000-0000-0000-bbbb22220000"
    stranger = "cccc3333-0000-0000-0000-cccc33330000"
    member_email = "member@example.com"
    headers_owner = _auth(_token(owner))
    headers_member = _auth(_token(member, email=member_email))
    headers_stranger = _auth(_token(stranger))

    ws = client.post("/api/v1/workspaces", json={"name": "Shared"}, headers=headers_owner).json()
    wid = ws["id"]

    # Owner creates a presentation and adds it to the workspace.
    pid = client.post(
        "/api/v1/presentations", json={"title": "Shared Deck"}, headers=headers_owner
    ).json()["id"]
    added = client.post(
        f"/api/v1/workspaces/{wid}/presentations",
        json={"presentation_id": pid},
        headers=headers_owner,
    )
    assert added.status_code == 201

    # Invite + accept the member.
    inv = client.post(
        f"/api/v1/workspaces/{wid}/invitations",
        json={"email": member_email, "role": "editor"},
        headers=headers_owner,
    ).json()
    acc = client.post(f"/api/v1/workspaces/invitations/{inv['id']}/accept", headers=headers_member)
    assert acc.status_code == 200

    # Member sees the full presentation in the workspace listing.
    listing = client.get(f"/api/v1/workspaces/{wid}/presentations", headers=headers_member)
    assert listing.status_code == 200
    body = listing.json()
    assert body["presentation_ids"] == [pid]
    assert [p["id"] for p in body["presentations"]] == [pid]
    assert body["presentations"][0]["title"] == "Shared Deck"

    # Member can GET the presentation (read access via workspace).
    got = client.get(f"/api/v1/presentations/{pid}", headers=headers_member)
    assert got.status_code == 200
    assert got.json()["title"] == "Shared Deck"

    # Editor role can update the spec (write access).
    gen = client.post(
        "/api/v1/presentations/generate",
        json={"prompt": "x", "slide_count": 1},
        headers=headers_owner,
    ).json()
    pid2 = gen["id"]
    # Make the generated deck owned by the owner but shared: add pid2 to workspace
    client.post(
        f"/api/v1/workspaces/{wid}/presentations",
        json={"presentation_id": pid2},
        headers=headers_owner,
    )
    spec = client.get(f"/api/v1/presentations/{pid2}/spec", headers=headers_owner).json()
    updated = client.put(f"/api/v1/presentations/{pid2}/spec", json=spec, headers=headers_member)
    assert updated.status_code == 200

    # A stranger (non-member) cannot see the shared deck.
    hidden = client.get(f"/api/v1/presentations/{pid}", headers=headers_stranger)
    assert hidden.status_code == 404


def test_workspace_presentations_requires_member(client: TestClient) -> None:
    owner = "cccccccc-2222-2222-2222-cccccccccccc"
    stranger = "dddddddd-3333-3333-3333-dddddddddddd"
    headers_owner = _auth(_token(owner))
    headers_stranger = _auth(_token(stranger))

    ws = client.post("/api/v1/workspaces", json={"name": "WS"}, headers=headers_owner).json()
    wid = ws["id"]

    res = client.post(
        f"/api/v1/workspaces/{wid}/presentations",
        json={"presentation_id": "eeeeeeee-4444-4444-4444-eeeeeeeeeeee"},
        headers=headers_stranger,
    )
    assert res.status_code == 404