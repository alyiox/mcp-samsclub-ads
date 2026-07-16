# Sam's Club Sponsored Ads APIs

[![CI](https://github.com/alyiox/mcp-samsclub-ads/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/alyiox/mcp-samsclub-ads/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/mcp-samsclub-ads.svg)](https://pypi.org/project/mcp-samsclub-ads/)
[![Python 3.13+](https://img.shields.io/badge/python-3.13%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

<!-- mcp-name: io.github.alyiox/mcp-samsclub-ads -->

MCP server for [Sam's Club Sponsored Ads APIs](https://developer.samsclub.com/API/overview/).

Exposes spec-driven discovery (`list_endpoints`, `describe_endpoint`), a generic API proxy (`call_endpoint`), and a runtime spec refresher (`refresh_specs`). The AI agent discovers endpoints from a bundled OpenAPI spec then calls them; the server handles RSA-SHA256 signing and auth headers automatically.

Forked from [`mcp-walmart-ads`](https://github.com/alyiox/mcp-walmart-ads): Sam's Club runs on the same Walmart api-proxy backend and uses the same `WM_*` signing headers, so the auth, HTTP client, discovery, caching, and tool surface carry over. The differences are a single `sponsored` ad family (vs Walmart's `search`/`display`), the Sam's Club base URLs, and a hand-authored OpenAPI spec.

## Features

- **Spec-driven discovery** — list/describe endpoints from a bundled OpenAPI spec, refreshable at runtime
- **Any endpoint** — call by operation id or raw method+path (raw path reaches endpoints not yet in the spec); no code changes when APIs evolve
- Multi-region, multi-environment (production + sandbox) via config file
- Per-request RSA-SHA256 signing with automatic header construction
- Large responses truncated with full data available via MCP resource URI

## Requirements

- Python 3.13+
- Sam's Club Partner credentials (consumer ID, RSA key pair, bearer token) — see [Status & blocker](#status--blocker)

## Quick start

Set up your config (see [Configuration](#configuration)), then run the server:

```bash
# Run directly with uvx (no clone needed)
npx -y @modelcontextprotocol/inspector uvx mcp-samsclub-ads
```

```bash
# Or run from source
git clone https://github.com/alyiox/mcp-samsclub-ads.git
cd mcp-samsclub-ads
uv sync
npx -y @modelcontextprotocol/inspector uv run mcp-samsclub-ads
```

The server speaks MCP over stdio.

## Configuration

The config file lives under your home directory at `~/.config/mcp-samsclub-ads/config.json`.

> **Windows note:** `~` maps to `%USERPROFILE%` (typically `C:\Users\<you>`), so the
> full path is `%USERPROFILE%\.config\mcp-samsclub-ads\config.json`.

**1. Create the config directory and copy the example**

```bash
# Unix-like (macOS, Linux, WSL, …)
mkdir -p ~/.config/mcp-samsclub-ads/keys/us
cp config.example.json ~/.config/mcp-samsclub-ads/config.json
```

```powershell
# Windows (PowerShell)
New-Item -ItemType Directory -Force "$env:USERPROFILE\.config\mcp-samsclub-ads\keys\us"
Copy-Item config.example.json "$env:USERPROFILE\.config\mcp-samsclub-ads\config.json"
```

**2. Edit `~/.config/mcp-samsclub-ads/config.json`**

```json
{
  "response_cache_ttl": 3600,
  "truncate_threshold": 51200,
  "regions": {
    "US": {
      "production": {
        "consumer_id": "your-consumer-id",
        "private_key": "./keys/us/prod.pem",
        "private_key_version": "1",
        "bearer_token": "your-bearer-token",
        "base_urls": {
          "sponsored": "https://developer.api.us.walmart.com/api-proxy/service/sp/api-sams/v1"
        }
      },
      "sandbox": {
        "consumer_id": "your-sandbox-consumer-id",
        "private_key": "./keys/us/sandbox.pem",
        "private_key_version": "1",
        "bearer_token": "your-sandbox-bearer-token",
        "base_urls": {
          "sponsored": "https://developer.api.us.stg.walmart.com/api-proxy/service/sp/api-sams/v1"
        }
      }
    }
  }
}
```

**3. Place your RSA private key PEM files in `~/.config/mcp-samsclub-ads/keys/`**

Key paths in the config are resolved relative to the config directory, so `./keys/us/prod.pem` resolves to `~/.config/mcp-samsclub-ads/keys/us/prod.pem`.

| Config field | Description |
|---|---|
| `response_cache_ttl` | Seconds to keep truncated responses in memory (default `3600`) |
| `truncate_threshold` | Response byte limit before truncation (default `51200`) |
| `regions.<R>.<E>.consumer_id` | Your Sam's Club consumer ID |
| `regions.<R>.<E>.private_key` | Path to RSA private key PEM (relative to config dir or absolute) |
| `regions.<R>.<E>.private_key_version` | Key version string (default `"1"`) |
| `regions.<R>.<E>.bearer_token` | OAuth bearer token |
| `regions.<R>.<E>.base_urls.sponsored` | Sponsored Ads API base URL |

Each request is signed with `WM_CONSUMER.ID`, `WM_SEC.AUTH_SIGNATURE` (Base64 RSA-SHA256), `WM_SEC.KEY_VERSION`, and `WM_CONSUMER.INTIMESTAMP` (Unix epoch ms), plus `Authorization: Bearer <token>` — all injected automatically by the client.

### Base URLs

- **Production:** `https://developer.api.us.walmart.com/api-proxy/service/sp/api-sams/v1`
- **Sandbox:** `https://developer.api.us.stg.walmart.com/api-proxy/service/sp/api-sams/v1`

Paths in the spec begin `/api/v1/...` (or `/api/v2/...`), so the effective URL is `<base_url>/api/v1/<resource>`.

## Tools

### `list_endpoints`

List operations from the bundled OpenAPI spec for an `ad_type`, with optional filters.

| Parameter | Required | Description |
|---|---|---|
| `ad_type` | yes | `sponsored` |
| `query` | no | Case-insensitive substring match on operationId, path, or summary |
| `tag` | no | Filter to operations whose OpenAPI tags include this value |
| `method` | no | Filter by HTTP verb |

### `describe_endpoint`

Return one operation plus the `components.schemas` reachable from it (its `$ref` closure), so request bodies and responses can be built without the full spec.

| Parameter | Required | Description |
|---|---|---|
| `ad_type` | yes | `sponsored` |
| `operation_id` | yes | Spec operation id (from `list_endpoints`) |

### `call_endpoint`

Execute any Sam's Club Sponsored Ads API endpoint. Identify it by `operation_id`, or by raw `method` + `path`. Raw method+path also reaches endpoints not yet in the bundled spec. The server handles RSA-SHA256 signing.

| Parameter | Required | Description |
|---|---|---|
| `region` | yes | e.g. `US` |
| `env` | yes | `production` or `sandbox` |
| `ad_type` | yes | `sponsored` |
| `operation_id` | no* | Spec operation id; resolves `method`+`path` |
| `method` | no* | `GET`, `POST`, `PUT`, `PATCH`, or `DELETE` |
| `path` | no* | e.g. `/api/v1/campaigns` |
| `params` | no | Query string parameters (JSON object) |
| `body` | no | JSON request body for POST/PUT (object or array) |

\* Provide either `operation_id`, or both `method` and `path`.

### `refresh_specs`

Re-fetch the bundled OpenAPI spec from its committed `source_url` into a user cache (`~/.cache/mcp-samsclub-ads/specs/`) that takes precedence over the bundled copy — ship fixes without a release.

| Parameter | Required | Description |
|---|---|---|
| `spec_id` | no | One spec to refresh (e.g. `sponsored/sponsored-ads`); omit to refresh all |

## MCP resources

Endpoint schemas come from the bundled OpenAPI spec via `list_endpoints` / `describe_endpoint` (see [Tools](#tools)), not from static resources.

### Dynamic resources

| Resource URI | Description |
|---|---|
| `sca://config` | Available regions, environments, and ad types from your config |
| `sca://responses/{request_id}` | Full body of a truncated API response (cached in memory, TTL from config) |
| `sca://curl/{request_id}` | Reproducible cURL command for a previous API request |

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

## MCP host examples

### Cursor

Add to `.cursor/mcp.json`:

```json
{
  "mcpServers": {
    "samsclub-ads": {
      "command": "uvx",
      "args": ["mcp-samsclub-ads"]
    }
  }
}
```

### Claude Code

Add to your Claude Code MCP config:

```json
{
  "mcpServers": {
    "samsclub-ads": {
      "command": "uvx",
      "args": ["mcp-samsclub-ads"]
    }
  }
}
```

### Codex

```toml
[mcp_servers.samsclub-ads]
command = "uvx"
args = ["mcp-samsclub-ads"]
```

### OpenCode

```json
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "samsclub-ads": {
      "type": "local",
      "enabled": true,
      "command": ["uvx", "mcp-samsclub-ads"]
    }
  }
}
```

### GitHub Copilot

```json
{
  "inputs": [],
  "servers": {
    "samsclub-ads": {
      "type": "stdio",
      "command": "uvx",
      "args": ["mcp-samsclub-ads"]
    }
  }
}
```

## Development

```bash
uv sync --group dev    # install deps
uv run pytest          # run tests
uv run ruff check .    # lint
uv run ruff format .   # format
uv run pyright         # type check
```

## Reference

- API docs: https://developer.samsclub.com/API/overview/
- Authentication: https://developer.samsclub.com/API/authentication/
- Base project: [`mcp-walmart-ads`](https://github.com/alyiox/mcp-walmart-ads)

## Contributing

Open issues or PRs. Follow existing style and add tests where appropriate.

## License

MIT. See [LICENSE](LICENSE).
