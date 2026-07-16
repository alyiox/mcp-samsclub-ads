# mcp-samsclub-ads

MCP server for Sam's Club Sponsored Ads APIs — spec-driven endpoint discovery and a
generic authenticated proxy with automatic RSA-SHA256 request signing.

Forked from [`mcp-walmart-ads`](https://github.com/alyiox/mcp-walmart-ads): Sam's Club runs
on the same Walmart api-proxy backend and uses the same `WM_*` signing headers, so the auth,
HTTP client, discovery, caching, and tool surface carry over. The differences are a single
`sponsored` ad family (vs Walmart's `search`/`display`), the Sam's Club base URLs, and a
hand-authored OpenAPI spec.

## Install & run

```bash
uvx mcp-samsclub-ads        # published
uv run mcp-samsclub-ads     # from source
```

The server speaks MCP over stdio.

## Configuration

Create `~/.config/mcp-samsclub-ads/config.json` from [`config.example.json`](config.example.json):

```json
{
  "regions": {
    "US": {
      "sandbox": {
        "consumer_id": "your-consumer-id",
        "private_key": "./keys/us/sandbox.pem",
        "private_key_version": "1",
        "bearer_token": "your-bearer-token",
        "base_urls": {
          "sponsored": "https://developer.api.us.stg.walmart.com/api-proxy/service/sp/api-sams/v1"
        }
      }
    }
  }
}
```

`private_key` is a path (relative paths resolve against the config dir) to your RSA private
key PEM. Each request is signed with `WM_CONSUMER.ID`, `WM_SEC.AUTH_SIGNATURE`
(Base64 RSA-SHA256), `WM_SEC.KEY_VERSION`, `WM_CONSUMER.INTIMESTAMP` (Unix epoch ms), plus
`Authorization: Bearer <token>` — all injected automatically by the client.

### Base URLs

- **Sandbox:** `https://developer.api.us.stg.walmart.com/api-proxy/service/sp/api-sams/v1`
- **Production:** `https://developer.api.us.walmart.com/api-proxy/service/sp/api-sams/v1`

Paths in the spec begin `/api/v1/...` (or `/api/v2/...`), so the effective URL is
`<base_url>/api/v1/<resource>`.

## Tools

- **`list_endpoints`** — list OpenAPI operations for an ad_type, filter by query/tag/method.
- **`describe_endpoint`** — one operation plus its transitive `components.schemas` closure.
- **`call_endpoint`** — execute a signed request by `operation_id` or by raw `method`+`path`.
  Raw path also reaches endpoints not yet in the bundled spec.
- **`refresh_specs`** — re-pull the committed spec from its `source_url` into a user cache
  that takes precedence over the bundle (ship fixes without a release).

Resources: `sca://config`, `sca://responses/{request_id}`, `sca://curl/{request_id}`.

## Spec coverage

The bundled OpenAPI spec is **hand-authored from the
[developer.samsclub.com](https://developer.samsclub.com/API/overview/) docs and is partial by
design.** It covers the core ads surface: Campaigns, Statistics, Ad Groups, Ad Items, Catalog
Item Search, Keywords (+ suggestions/analytics), Negative Keywords, Placements, Bid
Multipliers, and Snapshot Reports v1/v2 + Latest Report Date. Endpoints not yet modeled (SBA
profiles, media, reviews, api-usage, entity/audit snapshots, alerts & recommendations) are
still reachable via `call_endpoint` with a raw `method`+`path`.

## Status & blocker

**Partner credentials are the long pole.** Access requires emailing an RSA public key to
`partner-support@samsclub.com` and receiving a consumer id + auth token + key version.
Without sandbox credentials the server runs and its discovery/signing are verified offline,
but calls cannot be exercised end-to-end.

## Spec drift detection

[`scripts/build_spec.py`](scripts/build_spec.py) scrapes the docs into a *candidate* spec at
[`spec-candidate/`](spec-candidate/) — offline, never at runtime. The
[`Spec drift`](.github/workflows/spec-drift.yml) workflow runs it on a schedule and opens a
PR when the docs change; a reviewer then ports real changes into the hand-authored canonical
spec. The candidate is intentionally flat and is never shipped or loaded.

```bash
uv run --group spec-build python scripts/build_spec.py          # write candidate
uv run --group spec-build python scripts/build_spec.py --check  # exit 1 on drift
```

Still deferred: flipping a spec's `auth` flag to fetch the authenticated live Swagger backend
once partner credentials exist.

## Development

```bash
uv sync --group dev
uv run ruff check src/ tests/ && uv run ruff format --check src/ tests/
uv run pyright
uv run pytest
```

## Reference

- API docs: https://developer.samsclub.com/API/overview/
- Authentication: https://developer.samsclub.com/API/authentication/
- Base project: [`mcp-walmart-ads`](https://github.com/alyiox/mcp-walmart-ads)
