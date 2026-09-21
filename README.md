# Project Intelligence Atlassian

Read-only Atlassian integration boundary for Project Intelligence. It centralizes
Rovo MCP access, accepts signed Jira and Confluence Forge events, and dispatches
identifier-only targeted jobs to ingestion.

See [Current architecture](docs/ARCHITECTURE.md) for the complete component map,
identity model, event and read flows, recovery behavior, and activation status.
See [Current quality status](docs/QUALITY_STATUS.md) for verified tests and the
closed repository-hygiene decisions.

## Security boundary

The initial release is intentionally read-only. `READ_WRITE` or
`PI_ATLASSIAN_WRITE_ENABLED=true` fails configuration validation. MCP tool names
are checked against an allowlist and mutation attempts return
`ATLASSIAN_WRITE_DISABLED`. The service identity is for ingestion only; user-facing
live reads require a project-qualified user session registered by the backend.

The service resolves each event through the backend's active project catalog by
cloud and Jira-project/Confluence-space identity. It contains no T0 or T2.0
special case.

## Local development

1. Copy `.env.example` to `.env` and provide independent internal and Forge secrets.
2. Start the Docker stack, which exposes this service on `127.0.0.1:8005`.
3. Run `ngrok http 8005` and then `python scripts/register_ngrok_callback.py`.
4. Register, deploy, and install the Forge app after replacing the application ID.

The Forge application sends resource identifiers only. The ingestion service
rereads the authoritative parent resource before indexing. If Docker is offline,
the startup and five-minute cursor-based incremental runs repair missed events.
Daily authoritative reconciliation detects Confluence content deletions that
cannot be subscribed to while retaining strictly read-only Forge scopes.

## Interfaces

- `POST /v1/events/atlassian`: signed Forge deliveries.
- `PUT /v1/forge/callback`: register the active ngrok URL with Forge.
- `GET /v1/health`, `/v1/freshness`, `/v1/capabilities`: operational state.
- `GET /metrics`: content-free event, MCP, catch-up, queue, and latency metrics.
- `POST /v1/internal/search`: allowlisted Rovo MCP v2 reads.
- `POST /v1/internal/rest-read`: controlled REST fallback for complete pagination,
  attachment binaries, and deletion verification.
- `PUT/DELETE /v1/internal/sessions`: backend-only ephemeral user session lifecycle.
- `POST /v1/internal/mutations`: always returns `403 ATLASSIAN_WRITE_DISABLED`.

Rovo MCP uses `https://mcp.atlassian.com/v2/mcp?tools=all` and performs the
Streamable HTTP initialization handshake before tool execution. User sessions
use OAuth bearer tokens. A non-interactive service identity can use a service
account bearer key or `BASIC` mode with an Atlassian account email and a scoped
Rovo API token when the organization administrator permits token authentication.

## Current activation limits

Forge registration/deployment and Rovo authorization require Atlassian account
consent. Until a service token and Forge app ID are configured, the existing
read-only REST fallback and startup recovery remain usable, while MCP reads and
Forge events remain inactive.
