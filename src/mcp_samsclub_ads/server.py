from __future__ import annotations

import json
from typing import Annotated, Any

from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, Field, model_serializer

from . import discovery, specs
from .client import execute_request
from .config import load_config
from .resources import ResponseCache, read_cached_response
from .specs import SpecError

config = load_config()
cache = ResponseCache(ttl_seconds=config.response_cache_ttl)

mcp = FastMCP(
    "Sam's Club Sponsored Ads",
    instructions=(
        "MCP server for Sam's Club Sponsored Ads APIs. "
        "Discover endpoints with list_endpoints (filter by query/tag/method) "
        "and inspect one with describe_endpoint (returns the operation plus "
        "its schema closure). Execute with call_endpoint — by operation_id, or by raw "
        "method+path (raw path also reaches endpoints not yet in the bundled spec, "
        "which starts partial). The spec is bundled and can be refreshed at runtime "
        "from its committed source with refresh_specs."
    ),
)

# ── tool result models ─────────────────────────────────────────────────────────


class _ExcludeNone(BaseModel):
    @model_serializer(mode="wrap")
    def _exclude_none(self, handler: Any) -> dict[str, Any]:
        return {k: v for k, v in handler(self).items() if v is not None}


class ApiToolResult(_ExcludeNone):
    status_code: int | None = None
    body: Any | None = None
    truncated: bool | None = None
    cached_at: str | None = None  # sca://responses/{request_id}
    curl: str | None = None  # sca://curl/{request_id}
    error: str | None = None


# ── resources ──────────────────────────────────────────────────────────────────


@mcp.resource(
    "sca://config",
    name="config",
    description="[SamsClubAds] Available regions, environments, and ad types. Src: config.",
)
def get_config() -> str:
    result: dict[str, Any] = {}
    for region, envs in config.regions.items():
        result[region] = {}
        for env_name, env_cfg in envs.items():
            result[region][env_name] = list(env_cfg.base_urls.keys())
    return json.dumps({"regions": result}, indent=2)


@mcp.resource(
    "sca://responses/{request_id}",
    name="cached_response",
    description="[SamsClubAds] Retrieve full cached API response. Src: responses.",
)
def cached_response_resource(request_id: str) -> str:
    content = read_cached_response(request_id, cache)
    if content is None:
        return f"No cached response found for request_id={request_id} (may have expired)."
    return content


@mcp.resource(
    "sca://curl/{request_id}",
    name="request_curl",
    description="[SamsClubAds] Retrieve cURL command for a previous API request. Src: responses.",
)
def cached_curl_resource(request_id: str) -> str:
    data = cache.get(f"curl/{request_id}")
    if data is None:
        return f"No cURL command found for request_id={request_id} (may have expired)."
    return f"# cURL (auth headers are time-limited)\n\n{data}"


# ── tool ───────────────────────────────────────────────────────────────────────


@mcp.tool(
    name="call_endpoint",
    description=(
        "[SamsClubAds] Execute an authenticated Sam's Club Sponsored Ads API request. "
        "Identify the endpoint by operation_id (discovered via list_endpoints / "
        "describe_endpoint) or by raw method + path; raw method+path also reaches "
        "endpoints not yet in the bundled spec. Bodies over the configured byte "
        "threshold are truncated to a preview; read the returned cached_at resource "
        "(sca://responses/{request_id}) for full data. The result also carries a curl "
        "reference (sca://curl/{request_id})."
    ),
)
async def call_endpoint(
    region: Annotated[
        str,
        Field(description="[SamsClubAds] API region, e.g. US. Src: config."),
    ],
    env: Annotated[
        str,
        Field(description="[SamsClubAds] Target environment — production or sandbox. Src: config."),
    ],
    ad_type: Annotated[
        str,
        Field(description="[SamsClubAds] API family — sponsored. Src: config."),
    ],
    method: Annotated[
        str | None,
        Field(
            default=None,
            description=(
                "[SamsClubAds] HTTP method — GET, POST, PUT, PATCH, or DELETE. "
                "Required unless operation_id is given."
            ),
        ),
    ] = None,
    path: Annotated[
        str | None,
        Field(
            default=None,
            description=(
                "[SamsClubAds] API path after base URL, e.g. /api/v1/campaigns. "
                "Required unless operation_id is given."
            ),
        ),
    ] = None,
    operation_id: Annotated[
        str | None,
        Field(
            default=None,
            description=(
                "[SamsClubAds] Spec operation id (e.g. AdGroupList). Resolves "
                "method+path from the ad_type spec. Src: operations."
            ),
        ),
    ] = None,
    params: Annotated[
        dict[str, Any] | None,
        Field(
            default=None,
            description="[SamsClubAds] Query string parameters as a JSON object.",
        ),
    ] = None,
    body: Annotated[
        dict[str, Any] | list[Any] | None,
        Field(
            default=None,
            description=(
                "[SamsClubAds] JSON request body for POST/PUT "
                "(object or array when the API requires it)."
            ),
        ),
    ] = None,
) -> ApiToolResult:
    if region not in config.regions:
        available = ", ".join(config.regions.keys())
        msg = f"region '{region}' not found in config. Available: {available}"
        return ApiToolResult(error=msg)

    region_envs = config.regions[region]
    if env not in region_envs:
        available = ", ".join(region_envs.keys())
        msg = f"env '{env}' not found for region '{region}'. Available: {available}"
        return ApiToolResult(error=msg)

    ad_type_lower = ad_type.lower()
    if ad_type_lower not in ("sponsored",):
        return ApiToolResult(error="ad_type must be 'sponsored'.")

    if operation_id is not None:
        try:
            op = discovery.get_operation(ad_type_lower, operation_id)
        except SpecError as e:
            return ApiToolResult(error=str(e))
        method, path = op.method, op.path
    if not method or not path:
        return ApiToolResult(error="provide operation_id, or both method and path.")

    env_cfg = region_envs[env]

    if ad_type_lower not in env_cfg.base_urls:
        msg = f"base_url for ad_type '{ad_type}' not configured for {region}/{env}."
        return ApiToolResult(error=msg)

    response = await execute_request(
        cfg=env_cfg,
        ad_type=ad_type_lower,
        method=method,
        path=path,
        params=params,
        body=body,
    )

    cache.put(f"curl/{response.request_id}", response.curl)
    curl_ref = f"sca://curl/{response.request_id}"

    body_str = (
        json.dumps(response.body, indent=2) if not isinstance(response.body, str) else response.body
    )
    body_bytes = body_str.encode()

    if len(body_bytes) > config.truncate_threshold:
        cache.put(response.request_id, response.body)
        preview = body_str[: config.truncate_threshold].rsplit("\n", 1)[0] + "\n... (truncated)"
        return ApiToolResult(
            status_code=response.status_code,
            body=preview,
            truncated=True,
            cached_at=f"sca://responses/{response.request_id}",
            curl=curl_ref,
        )

    return ApiToolResult(
        status_code=response.status_code,
        body=response.body,
        curl=curl_ref,
    )


# ── discovery + refresh tools ────────────────────────────────────────────────


@mcp.tool(
    name="list_endpoints",
    description="[SamsClubAds] List OpenAPI operations for an ad_type with optional filters.",
)
async def list_endpoints(
    ad_type: Annotated[
        str,
        Field(description="[SamsClubAds] API family — sponsored. Src: config."),
    ],
    query: Annotated[
        str | None,
        Field(
            default=None,
            description=(
                "[SamsClubAds] Case-insensitive substring match on operationId, path, or summary."
            ),
        ),
    ] = None,
    tag: Annotated[
        str | None,
        Field(
            default=None,
            description="[SamsClubAds] Filter to operations whose OpenAPI tags include this value.",
        ),
    ] = None,
    method: Annotated[
        str | None,
        Field(
            default=None,
            description="[SamsClubAds] Filter by HTTP verb — GET, POST, PUT, PATCH, or DELETE.",
        ),
    ] = None,
) -> dict[str, Any]:
    try:
        endpoints = discovery.list_endpoints(ad_type.lower(), query=query, tag=tag, method=method)
    except SpecError as e:
        return {"error": str(e)}
    return {"ad_type": ad_type.lower(), "count": len(endpoints), "endpoints": endpoints}


@mcp.tool(
    name="describe_endpoint",
    description=(
        "[SamsClubAds] Describe one OpenAPI operation with its schema closure. "
        "Returns the operation plus every components.schemas entry reachable from "
        "it, so request bodies and responses can be built without the full spec."
    ),
)
async def describe_endpoint(
    ad_type: Annotated[
        str,
        Field(description="[SamsClubAds] API family — sponsored. Src: config."),
    ],
    operation_id: Annotated[
        str,
        Field(description="[SamsClubAds] Spec operation id. Src: operations."),
    ],
) -> dict[str, Any]:
    try:
        return discovery.describe_endpoint(ad_type.lower(), operation_id)
    except SpecError as e:
        return {"error": str(e)}


@mcp.tool(
    name="refresh_specs",
    description=(
        "[SamsClubAds] Refresh the bundled OpenAPI spec from its committed source. "
        "Re-fetches the latest spec JSON into a user cache that takes precedence "
        "over the bundled copy. Omit spec_id to refresh all specs."
    ),
)
async def refresh_specs(
    spec_id: Annotated[
        str | None,
        Field(
            default=None,
            description="[SamsClubAds] Spec id — sponsored/sponsored-ads. Src: specs.",
        ),
    ] = None,
) -> dict[str, Any]:
    try:
        results = await specs.refresh(spec_id)
    except SpecError as e:
        return {"error": str(e)}
    return {"refreshed": results}


# ── entry point ────────────────────────────────────────────────────────────────


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
