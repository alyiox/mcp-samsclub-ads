from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from mcp_samsclub_ads import discovery, specs
from mcp_samsclub_ads.specs import SpecError

# Path counts lock the bundled hand-authored spec.
_EXPECTED_PATHS = {
    "sponsored/sponsored-ads": 18,
}

# Operations across all verbs in the bundled spec.
_EXPECTED_OPERATIONS = 34


def test_manifest_matches_bundled_files() -> None:
    bundled = {
        str(p.relative_to(specs.BUNDLE_DIR)).replace("\\", "/").removesuffix(".openapi.json")
        for p in specs.BUNDLE_DIR.rglob("*.openapi.json")
    }
    manifest = {m.spec_id for m in specs.SPECS}
    assert manifest == bundled


@pytest.mark.parametrize("spec_id,count", _EXPECTED_PATHS.items())
def test_load_bundled_spec(spec_id: str, count: int) -> None:
    spec = specs.load_spec(spec_id)
    assert spec["openapi"].startswith("3.")
    assert len(spec["paths"]) == count


def test_load_unknown_spec_raises() -> None:
    with pytest.raises(SpecError):
        specs.load_spec("sponsored/does-not-exist")


def test_cache_overrides_bundle(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(specs, "cache_dir", lambda: tmp_path)
    meta = specs.meta_for("sponsored/sponsored-ads")
    sentinel = {"openapi": "3.0.1", "paths": {"/sentinel": {}}}
    specs._write_cache(specs.cache_path(meta), sentinel)
    assert specs.load_spec("sponsored/sponsored-ads") == sentinel


@pytest.mark.asyncio
async def test_refresh_writes_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(specs, "cache_dir", lambda: tmp_path)
    fake = {"openapi": "3.0.1", "info": {"version": "9.9"}, "paths": {"/x": {}}}
    monkeypatch.setattr(specs, "fetch_spec", lambda source_url, **kw: fake)

    rows = await specs.refresh("sponsored/sponsored-ads")
    assert len(rows) == 1
    assert rows[0]["status"] == "written"
    assert rows[0]["version"] == "9.9"
    assert rows[0]["source_url"] == specs.meta_for("sponsored/sponsored-ads").source_url
    written = json.loads((tmp_path / "sponsored" / "sponsored-ads.openapi.json").read_text())
    assert written == fake


@pytest.mark.asyncio
async def test_refresh_reports_per_spec_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(specs, "cache_dir", lambda: tmp_path)

    def boom(source_url: str, **kw: object) -> dict:
        raise httpx.ConnectError("offline")

    monkeypatch.setattr(specs, "fetch_spec", boom)
    rows = await specs.refresh()
    assert len(rows) == len(specs.SPECS)
    assert all(r["status"] == "error" for r in rows)


# ── discovery ────────────────────────────────────────────────────────────────


def test_list_endpoints_sponsored() -> None:
    result = discovery.list_endpoints("sponsored")
    assert len(result) == _EXPECTED_OPERATIONS
    assert all({"operation_id", "method", "path"} <= r.keys() for r in result)


def test_list_endpoints_filters() -> None:
    by_method = discovery.list_endpoints("sponsored", method="get")
    assert by_method and all(r["method"] == "GET" for r in by_method)
    by_query = discovery.list_endpoints("sponsored", query="campaign")
    assert by_query and all(
        "campaign" in r["operation_id"].lower()
        or "campaign" in r["path"].lower()
        or "campaign" in r["summary"].lower()
        for r in by_query
    )
    by_tag = discovery.list_endpoints("sponsored", tag="Keywords")
    assert by_tag and all("Keywords" in r["tags"] for r in by_tag)


def test_describe_endpoint_resolves_refs() -> None:
    desc = discovery.describe_endpoint("sponsored", "CampaignCreate")
    assert desc["operation_id"] == "CampaignCreate"
    assert desc["method"] == "POST"
    schemas = desc["components"]["schemas"]
    # CampaignCreate's request body ref plus the transitive CampaignResult closure.
    assert "CampaignCreate" in schemas
    assert "CampaignResult" in schemas
    assert "MutationResult" in schemas


def test_describe_unknown_operation_raises() -> None:
    with pytest.raises(SpecError):
        discovery.describe_endpoint("sponsored", "NoSuchOperation")


def test_get_operation_unknown_ad_type_raises() -> None:
    with pytest.raises(SpecError):
        discovery.get_operation("video", "whatever")
