"""Tests for the asset engine."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


class TestPlaceholderProvider:
    from app.assets.provider import PlaceholderProvider

    def test_returns_images(self) -> None:
        import asyncio
        from app.assets.provider import PlaceholderProvider

        provider = PlaceholderProvider()
        results = asyncio.get_event_loop().run_until_complete(provider.search("nature", 5))
        assert len(results) == 5
        assert all(r.kind.value == "image" for r in results)
        assert all(r.url.startswith("https://picsum.photos") for r in results)


class TestSvgIconProvider:
    def test_returns_icons(self) -> None:
        import asyncio
        from app.assets.provider import SvgIconProvider

        provider = SvgIconProvider()
        results = asyncio.get_event_loop().run_until_complete(provider.search("star", 12))
        assert len(results) >= 1
        assert all(r.kind.value == "icon" for r in results)
        assert all("star" in r.id for r in results)

    def test_all_icons_when_no_query(self) -> None:
        import asyncio
        from app.assets.provider import SvgIconProvider

        provider = SvgIconProvider()
        results = asyncio.get_event_loop().run_until_complete(provider.search("", 20))
        assert len(results) > 5


class TestAssetRegistry:
    def test_routing_by_kind(self) -> None:
        import asyncio
        from app.assets.provider import AssetKind, build_asset_registry

        registry = build_asset_registry()
        images = asyncio.get_event_loop().run_until_complete(registry.search("test", AssetKind.IMAGE, 3))
        assert len(images) == 3
        assert all(r.kind == AssetKind.IMAGE for r in images)

    def test_cache_hit(self) -> None:
        import asyncio
        from app.assets.provider import AssetKind, build_asset_registry

        registry = build_asset_registry()
        loop = asyncio.get_event_loop()
        r1 = loop.run_until_complete(registry.search("tech", AssetKind.IMAGE, 4))
        r2 = loop.run_until_complete(registry.search("tech", AssetKind.IMAGE, 4))
        assert [r.id for r in r1] == [r.id for r in r2]


def test_search_endpoint(client: TestClient) -> None:
    res = client.get("/api/v1/assets/search?q=technology&kind=image&limit=6")
    assert res.status_code == 200
    body = res.json()
    assert body["total"] == 6
    assert len(body["items"]) == 6
    assert all(item["kind"] == "image" for item in body["items"])


def test_search_icons(client: TestClient) -> None:
    res = client.get("/api/v1/assets/search?q=star&kind=icon")
    assert res.status_code == 200
    body = res.json()
    assert body["total"] >= 1
    assert all(item["kind"] == "icon" for item in body["items"])
