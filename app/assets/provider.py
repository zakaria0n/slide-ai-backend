"""Asset provider abstraction and registry.

Providers return lists of AssetRef objects for images, icons, and SVGs.
The registry resolves by kind with in-memory TTL caching.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from cachetools import TTLCache


class AssetKind(str, Enum):
    IMAGE = "image"
    ICON = "icon"
    SVG = "svg"


@dataclass
class AssetRef:
    id: str
    kind: AssetKind
    url: str
    thumbnail: str | None = None
    attribution: str | None = None
    provider: str = ""


class AssetProvider(ABC):
    """Contract for searching assets of a specific kind."""

    @property
    @abstractmethod
    def kind(self) -> AssetKind: ...

    @abstractmethod
    async def search(self, query: str, limit: int = 12) -> list[AssetRef]:
        ...


class PlaceholderProvider(AssetProvider):
    """Deterministic placeholder images from picsum.photos."""

    kind = AssetKind.IMAGE
    provider = "placeholder"

    async def search(self, query: str, limit: int = 12) -> list[AssetRef]:
        refs: list[AssetRef] = []
        for i in range(min(limit, 12)):
            seed = f"{query}-{i}".replace(" ", "-")
            url = f"https://picsum.photos/seed/{seed}/800/600"
            thumb = f"https://picsum.photos/seed/{seed}/200/150"
            refs.append(AssetRef(
                id=f"placeholder-{seed}",
                kind=AssetKind.IMAGE,
                url=url,
                thumbnail=thumb,
                attribution="Picsum Photos",
                provider=self.provider,
            ))
        return refs


class SvgIconProvider(AssetProvider):
    """Static inline SVG icons (bundled, no network)."""

    kind = AssetKind.ICON
    provider = "svg-icons"

    _ICONS: dict[str, str] = {
        "spark": '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3v18"/><path d="m5 12 7 7 7-7"/></svg>',
        "heart": '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M19 14c1.49-1.46 3-3.21 3-5.5A5.5 5.5 0 0 0 16.5 3c-1.76 0-3 .5-4.5 2-1.5-1.5-2.74-2-4.5-2A5.5 5.5 0 0 0 2 8.5c0 2.3 1.5 4.05 3 5.5l7 7Z"/></svg>',
        "star": '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/></svg>',
        "check": '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6 9 17l-5-5"/></svg>',
        "circle": '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/></svg>',
        "zap": '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg>',
        "globe": '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="M12 2a14.5 14.5 0 0 0 0 20 14.5 14.5 0 0 0 0-20"/><path d="M2 12h20"/></svg>',
        "clock": '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>',
        "arrow-up": '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m5 12 7-7 7 7"/><path d="M12 19V5"/></svg>',
        "layers": '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m12.83 2.18a2 2 0 0 0-1.66 0L2.6 6.08a1 1 0 0 0 0 1.83l8.58 3.91a2 2 0 0 0 1.66 0l8.58-3.9a1 1 0 0 0 0-1.83Z"/><path d="m2 12 8.58 3.91a2 2 0 0 0 1.66 0L22 12"/><path d="m2 17 8.58 3.91a2 2 0 0 0 1.66 0L22 17"/></svg>',
    }

    async def search(self, query: str, limit: int = 12) -> list[AssetRef]:
        q = query.lower()
        matching = [
            (name, svg) for name, svg in self._ICONS.items()
            if q in name or not q
        ]
        return [
            AssetRef(
                id=f"icon-{name}",
                kind=AssetKind.ICON,
                url=f"data:image/svg+xml,{svg}",
                thumbnail=f"data:image/svg+xml,{svg}",
                provider=self.provider,
            )
            for name, svg in matching[:limit]
        ]


class UnsplashReadyProvider(AssetProvider):
    """Returns Unsplash source URLs (no API key required)."""

    kind = AssetKind.IMAGE
    provider = "unsplash"

    async def search(self, query: str, limit: int = 12) -> list[AssetRef]:
        refs: list[AssetRef] = []
        for i in range(min(limit, 12)):
            url = f"https://source.unsplash.com/800x600/?{query}&sig={i}"
            thumb = f"https://source.unsplash.com/200x150/?{query}&sig={i}"
            refs.append(AssetRef(
                id=f"unsplash-{query}-{i}",
                kind=AssetKind.IMAGE,
                url=url,
                thumbnail=thumb,
                attribution="Unsplash",
                provider=self.provider,
            ))
        return refs


class PexelsReadyProvider(AssetProvider):
    """Returns Pexels search URL patterns."""

    kind = AssetKind.IMAGE
    provider = "pexels"

    async def search(self, query: str, limit: int = 12) -> list[AssetRef]:
        refs: list[AssetRef] = []
        for i in range(min(limit, 12)):
            url = f"https://images.pexels.com/photos/{1000000 + i}/pexels-photo-{1000000 + i}.jpeg?auto=compress&cs=tinysrgb&w=800"
            thumb = url.replace("w=800", "w=200")
            refs.append(AssetRef(
                id=f"pexels-{query}-{i}",
                kind=AssetKind.IMAGE,
                url=url,
                thumbnail=thumb,
                attribution="Pexels",
                provider=self.provider,
            ))
        return refs


class AssetRegistry:
    """Resolves asset kind to provider, with in-memory TTL cache."""

    def __init__(self, ttl_seconds: int = 300, max_size: int = 200) -> None:
        self._providers: dict[AssetKind, AssetProvider] = {}
        self._cache: TTLCache[str, list[AssetRef]] = TTLCache(maxsize=max_size, ttl=ttl_seconds)

    def register(self, provider: AssetProvider) -> None:
        self._providers[provider.kind] = provider

    async def search(self, query: str, kind: AssetKind = AssetKind.IMAGE, limit: int = 12) -> list[AssetRef]:
        cache_key = f"{kind.value}:{query}:{limit}"
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        provider = self._providers.get(kind)
        if provider is None:
            return []

        results = await provider.search(query, limit)
        self._cache[cache_key] = results
        return results

    def available_kinds(self) -> list[AssetKind]:
        return list(self._providers.keys())


def build_asset_registry() -> AssetRegistry:
    """Create a fully-wired asset registry."""
    registry = AssetRegistry()
    registry.register(PlaceholderProvider())
    registry.register(SvgIconProvider())
    registry.register(UnsplashReadyProvider())
    registry.register(PexelsReadyProvider())
    return registry
