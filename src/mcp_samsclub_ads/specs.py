"""OpenAPI spec bundling, caching, and runtime refresh.

No public OpenAPI spec is published for the Sam's Club Sponsored Ads API, so the
canonical spec is hand-authored from the developer.samsclub.com docs and bundled
in the package (``specs/<ad_type>/<name>.openapi.json``) — the server works fully
offline. ``refresh_specs`` re-pulls the latest committed spec from its
``source_url`` (the raw URL of the spec file in the repo) into a user-scoped
cache dir, which then takes precedence over the bundle. That lets hand
corrections ship to users without a package release.

Each ``SpecMeta`` also carries an ``auth`` flag. It is ``False`` today (the
``source_url`` is public raw content, fetched with a plain GET). Once partner
credentials are available a spec can be pointed at the authenticated live
Swagger backend and flipped to ``auth=True``, so ``fetch_spec`` attaches the
signed ``WM_*``/Bearer headers.

Load precedence: user cache dir → bundled package copy.
"""

from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

BUNDLE_DIR = Path(__file__).parent / "specs"


class SpecError(Exception):
    """Raised when a spec is missing, unfetchable, or malformed."""


@dataclass(frozen=True)
class SpecMeta:
    """One bundled OpenAPI spec and where ``refresh_specs`` re-pulls it from.

    ``ad_type`` is ``sponsored`` for the canonical spec that backs the discovery
    + execution surface; ``None`` for auxiliary specs that are bundled and
    refreshable but not part of the ad_type-keyed API surface.

    ``source_url`` is where ``refresh`` fetches the latest spec — normally the
    raw URL of the committed spec file, so fixes ship without a release. When
    ``auth`` is ``True`` the URL is the authenticated live Swagger backend and
    the fetch is signed with the caller's ``WM_*``/Bearer headers.
    """

    spec_id: str
    source_url: str
    ad_type: str | None
    auth: bool = False

    @property
    def rel_path(self) -> str:
        return f"{self.spec_id}.openapi.json"


# Raw URL of the committed spec. Refreshing requires this to resolve at runtime;
# if the repo is private, point it at a public raw-content host or an
# authenticated source (auth=True). See README / plan "open item".
_SPONSORED_SOURCE_URL = (
    "https://raw.githubusercontent.com/alyiox/mcp-samsclub-ads/main/"
    "src/mcp_samsclub_ads/specs/sponsored/sponsored-ads.openapi.json"
)

SPECS: tuple[SpecMeta, ...] = (
    SpecMeta("sponsored/sponsored-ads", _SPONSORED_SOURCE_URL, "sponsored", auth=False),
)

# ad_type → canonical spec_id (discovery + execution surface).
AD_TYPE_SPEC: dict[str, str] = {m.ad_type: m.spec_id for m in SPECS if m.ad_type}

_refresh_lock = asyncio.Lock()


def cache_dir() -> Path:
    """User-scoped cache root for refreshed specs."""
    return Path.home() / ".cache" / "mcp-samsclub-ads" / "specs"


def meta_for(spec_id: str) -> SpecMeta:
    for meta in SPECS:
        if meta.spec_id == spec_id:
            return meta
    known = ", ".join(m.spec_id for m in SPECS)
    raise SpecError(f"unknown spec_id {spec_id!r} (known: {known})")


def bundled_path(meta: SpecMeta) -> Path:
    return BUNDLE_DIR / meta.rel_path


def cache_path(meta: SpecMeta) -> Path:
    return cache_dir() / meta.rel_path


def load_spec(spec_id: str) -> dict[str, Any]:
    """Load a spec, preferring the cached (refreshed) copy over the bundle."""
    meta = meta_for(spec_id)
    for path in (cache_path(meta), bundled_path(meta)):
        if not path.is_file():
            continue
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            raise SpecError(f"spec {spec_id!r} at {path} is not valid JSON: {e}") from e
    raise SpecError(f"no spec file found for {spec_id!r}")


def fetch_spec(
    source_url: str,
    *,
    auth: bool = False,
    headers: dict[str, str] | None = None,
    timeout: float = 30.0,
) -> dict[str, Any]:
    """Download a spec from ``source_url``.

    Unauthenticated GET by default. When ``auth`` is ``True`` the caller's signed
    ``WM_*``/Bearer ``headers`` are attached (for the future live Swagger source).
    Synchronous so the network call can run off the event loop via
    ``asyncio.to_thread``.
    """
    request_headers = headers if (auth and headers) else None
    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        response = client.get(source_url, headers=request_headers)
        response.raise_for_status()
        return response.json()


def _write_cache(target: Path, spec: dict[str, Any]) -> None:
    """Atomically write a spec to the cache (reader never sees a partial file)."""
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + ".tmp")
    tmp.write_text(json.dumps(spec, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, target)


async def refresh(spec_id: str | None = None) -> list[dict[str, Any]]:
    """Re-fetch one spec (by id) or all, writing each to the user cache.

    Per-spec errors are reported in the result row rather than aborting the
    batch. Returns one row per spec with ``status`` ``written``/``error``.
    """
    metas = [meta_for(spec_id)] if spec_id is not None else list(SPECS)
    results: list[dict[str, Any]] = []
    async with _refresh_lock:
        for meta in metas:
            try:
                spec = await asyncio.to_thread(fetch_spec, meta.source_url, auth=meta.auth)
                await asyncio.to_thread(_write_cache, cache_path(meta), spec)
            except (httpx.HTTPError, json.JSONDecodeError, OSError) as e:
                results.append({"spec_id": meta.spec_id, "status": "error", "error": str(e)})
                continue
            info = spec.get("info") or {}
            results.append(
                {
                    "spec_id": meta.spec_id,
                    "ad_type": meta.ad_type,
                    "status": "written",
                    "source_url": meta.source_url,
                    "version": info.get("version"),
                    "paths": len(spec.get("paths") or {}),
                    "cached_at": str(cache_path(meta)),
                }
            )
    return results
