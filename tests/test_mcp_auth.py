"""Tests for 30-day MCP tokens, device flow, OAuth server and the skill zip."""
from __future__ import annotations

import io
import zipfile


def _headers(uid: str) -> dict:
    from tests.test_generation_routes import _auth, _token

    return _auth(_token(uid))


# --- 30-day MCP token ---------------------------------------------------------


def test_mcp_token_is_30_days(client) -> None:
    res = client.post("/api/v1/auth/mcp-token", headers=_headers("12345678-1234-1234-1234-123456789012"))
    assert res.status_code == 200
    assert res.json()["expires_in"] == 30 * 24 * 3600


# --- device flow ----------------------------------------------------------------


def test_device_flow_full_pairing(client) -> None:
    # 1. Start pairing.
    start = client.post("/api/v1/auth/device/start")
    assert start.status_code == 200
    body = start.json()
    assert body["user_code"] and body["device_code"]

    # 2. Poll before approval → pending.
    pending = client.post("/api/v1/auth/device/poll", json={"device_code": body["device_code"]})
    assert pending.status_code == 200
    assert pending.json()["status"] == "pending"

    # 3. Approve in the browser (authenticated).
    approve = client.post(
        "/api/v1/auth/device/authorize",
        json={"user_code": body["user_code"]},
        headers=_headers("12345678-1234-1234-1234-123456789012"),
    )
    assert approve.status_code == 200, approve.text

    # 4. Poll → approved with a working 30-day token.
    done = client.post("/api/v1/auth/device/poll", json={"device_code": body["device_code"]}).json()
    assert done["status"] == "approved"
    assert done["expires_in"] >= 30 * 24 * 3600 - 60

    me = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {done['access_token']}"},
    )
    assert me.status_code == 200


def test_device_poll_unknown_code(client) -> None:
    res = client.post("/api/v1/auth/device/poll", json={"device_code": "nope"})
    assert res.status_code == 404


def test_device_authorize_unknown_code(client) -> None:
    res = client.post(
        "/api/v1/auth/device/authorize",
        json={"user_code": "ZZZZ-ZZZZ"},
        headers=_headers("12345678-1234-1234-1234-123456789012"),
    )
    assert res.status_code == 404


def test_device_authorize_requires_auth(client) -> None:
    res = client.post("/api/v1/auth/device/authorize", json={"user_code": "ABCD-1234"})
    assert res.status_code == 401


# --- OAuth2 server ----------------------------------------------------------------


def test_oauth_metadata_endpoints(client) -> None:
    meta = client.get("/api/v1/.well-known/oauth-authorization-server")
    assert meta.status_code == 200
    body = meta.json()
    assert body["registration_endpoint"].endswith("/oauth/register")
    assert "S256" in body["code_challenge_methods_supported"]

    pr = client.get("/api/v1/.well-known/oauth-protected-resource")
    assert pr.status_code == 200
    assert pr.json()["authorization_servers"]


def test_oauth_full_authorization_code_flow(client) -> None:
    # 1. Dynamic client registration.
    reg = client.post(
        "/api/v1/oauth/register",
        json={"redirect_uris": ["http://localhost:1/callback"], "client_name": "Test CLI"},
    )
    assert reg.status_code == 200
    client_id = reg.json()["client_id"]

    # 2. Authorize endpoint 302s to the web consent page.
    auth_req = client.get(
        "/api/v1/oauth/authorize",
        params={
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": "http://localhost:1/callback",
            "state": "st4te",
            "code_challenge": "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM",
            "code_challenge_method": "S256",
        },
        follow_redirects=False,
    )
    assert auth_req.status_code == 302
    consent_url = auth_req.headers["location"]
    assert "/oauth/authorize?auth_id=" in consent_url
    auth_id = consent_url.split("auth_id=")[1].split("&")[0]

    # 3. Approve with the web session.
    approve = client.post(
        "/api/v1/oauth/authorize/approve",
        json={"auth_id": auth_id},
        headers=_headers("12345678-1234-1234-1234-123456789012"),
    )
    assert approve.status_code == 200, approve.text
    redirect = approve.json()["redirect"]
    assert "code=" in redirect and "state=st4te" in redirect
    code = redirect.split("code=")[1].split("&")[0]

    # 4. PKCE verification is enforced.
    bad = client.post(
        "/api/v1/oauth/token",
        json={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": "http://localhost:1/callback",
            "code_verifier": "wrong-verifier",
        },
    )
    assert bad.status_code == 400

    # 5. Correct verifier → 30-day access token + refresh token.
    ok = client.post(
        "/api/v1/oauth/token",
        json={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": "http://localhost:1/callback",
            "code_verifier": "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk",
        },
    )
    assert ok.status_code == 200, ok.text
    tokens = ok.json()
    assert tokens["expires_in"] == 30 * 24 * 3600
    assert tokens["refresh_token"]

    # 5b. FORM-URLENCODED exchange (how real OAuth clients send it).
    def _get_code() -> tuple[str, str]:
        loc = client.get(
            "/api/v1/oauth/authorize",
            params={
                "response_type": "code",
                "client_id": client_id,
                "redirect_uri": "http://localhost:1/callback",
                "state": "st4te",
                "code_challenge": "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM",
                "code_challenge_method": "S256",
            },
            follow_redirects=False,
        ).headers["location"]
        auth_id = loc.split("auth_id=")[1].split("&")[0]
        approved = client.post(
            "/api/v1/oauth/authorize/approve",
            json={"auth_id": auth_id},
            headers=_headers("12345678-1234-1234-1234-123456789012"),
        ).json()
        return approved["redirect"].split("code=")[1].split("&")[0]

    form = client.post(
        "/api/v1/oauth/token",
        data={
            "grant_type": "authorization_code",
            "code": _get_code(),
            "redirect_uri": "http://localhost:1/callback",
            "code_verifier": "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk",
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert form.status_code == 200, form.text
    assert form.json()["access_token"]

    # 6. Refresh grant rotates.
    refreshed = client.post(
        "/api/v1/oauth/token",
        json={"grant_type": "refresh_token", "refresh_token": tokens["refresh_token"]},
    )
    assert refreshed.status_code == 200
    assert refreshed.json()["access_token"]


# --- skill zip ----------------------------------------------------------------------


def test_skill_zip_download(client) -> None:
    res = client.get("/api/v1/skill/slide-ai.zip")
    assert res.status_code == 200
    assert res.headers["content-type"] == "application/zip"
    zf = zipfile.ZipFile(io.BytesIO(res.content))
    names = zf.namelist()
    assert "slide-ai/SKILL.md" in names
    skill = zf.read("slide-ai/SKILL.md").decode().lower()
    assert "build decks" in skill and "yourself" in skill
    assert "never delegate" in skill
    assert "diagram" in skill and "algorithm" in skill
    assert "create_presentation" in skill
