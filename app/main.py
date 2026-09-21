import asyncio
import base64
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Annotated
from urllib.parse import quote

import httpx
from fastapi import FastAPI, Header, HTTPException, Request, Response, status
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from app.config import Settings, get_settings
from app.coordinator import EventCoordinator
from app.mcp import RovoMcpClient
from app.models import (
    AtlassianEvent,
    CallbackRequest,
    EventAcceptance,
    McpResult,
    MutationRequest,
    RestReadRequest,
    SearchRequest,
    SessionRegistration,
)
from app.security import ReadOnlyToolPolicy, authorize_internal, verify_forge_signature
from app.telemetry import EVENTS, MCP_CALLS


def create_app(settings: Settings | None = None) -> FastAPI:
    configured = settings or get_settings()
    coordinator = EventCoordinator(configured)
    policy = ReadOnlyToolPolicy()
    user_sessions: dict[tuple[str, str], SessionRegistration] = {}
    mcp_clients: dict[str, tuple[str, RovoMcpClient]] = {}

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        await coordinator.start()
        catch_up = asyncio.create_task(coordinator.recovery_loop())
        yield
        if not catch_up.done():
            catch_up.cancel()
        await coordinator.stop()

    app = FastAPI(title="Project Intelligence Atlassian", version="0.1.0", lifespan=lifespan)
    app.state.coordinator = coordinator

    @app.get("/v1/health")
    async def health():
        return {
            "status": "ok",
            "environment": configured.environment,
            "accessMode": configured.access_mode,
        }

    @app.get("/v1/capabilities")
    async def capabilities():
        return {
            "read": ["search", "get", "list", "read", "lookup", "fetch"],
            "write": [],
            "writeEnabled": False,
            "transports": ["ROVO_MCP", "REST_FALLBACK"],
        }

    @app.get("/metrics", include_in_schema=False)
    async def metrics():
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    @app.get("/v1/freshness")
    async def freshness():
        value = coordinator.last_success_at
        scopes = {
            key: {
                **scope,
                **(
                    {
                        "lastCompletedAt": datetime.fromtimestamp(
                            float(scope["lastCompletedAt"]), UTC
                        ).isoformat()
                    }
                    if scope.get("lastCompletedAt")
                    else {}
                ),
            }
            for key, scope in coordinator.freshness_by_scope.items()
        }
        return {
            "state": "FRESH" if value and not coordinator.last_failure else "CATCHING_UP",
            "lastEventCompletedAt": datetime.fromtimestamp(value, UTC).isoformat()
            if value
            else None,
            "lastFailure": coordinator.last_failure,
            "pending": coordinator.queue.qsize() + len(coordinator.pending),
            "scopes": scopes,
        }

    @app.put("/v1/forge/callback")
    async def configure_callback(
        body: CallbackRequest, x_internal_api_key: Annotated[str | None, Header()] = None
    ):
        authorize_internal(x_internal_api_key, configured.internal_api_key)
        if not configured.forge_config_url or not configured.forge_config_secret:
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "Forge configuration endpoint is not configured.",
            )
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                configured.forge_config_url,
                headers={"Authorization": f"Bearer {configured.forge_config_secret}"},
                json=body.model_dump(by_alias=True),
            )
        response.raise_for_status()
        return {"configured": True, "url": body.url}

    @app.post(
        "/v1/events/atlassian",
        response_model=EventAcceptance,
        response_model_by_alias=True,
        status_code=202,
    )
    async def event(
        request: Request,
        x_atlassian_signature_256: Annotated[str | None, Header()] = None,
        x_atlassian_timestamp: Annotated[str | None, Header()] = None,
    ):
        body = await request.body()
        if len(body) > configured.event_max_bytes:
            raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "Atlassian event is too large.")
        verify_forge_signature(
            body,
            x_atlassian_signature_256,
            x_atlassian_timestamp,
            configured.forge_webhook_secret,
            configured.event_max_age_seconds,
        )
        parsed = AtlassianEvent.model_validate_json(body)
        if parsed.self_generated:
            EVENTS.labels("ignored_self", parsed.resource_type.value).inc()
            return EventAcceptance(
                accepted=False, reason="Self-generated event ignored.", eventId=parsed.event_id
            )
        accepted = await coordinator.accept(parsed)
        EVENTS.labels("accepted" if accepted else "duplicate", parsed.resource_type.value).inc()
        return EventAcceptance(
            accepted=accepted,
            duplicate=not accepted,
            reason="Accepted." if accepted else "Duplicate event.",
            eventId=parsed.event_id,
        )

    @app.post("/v1/internal/search", response_model=McpResult)
    async def search(
        body: SearchRequest, x_internal_api_key: Annotated[str | None, Header()] = None
    ):
        authorize_internal(x_internal_api_key, configured.internal_api_key)
        policy.authorize(body.tool)
        if body.identity_class == "USER":
            if not body.user_id:
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_CONTENT,
                    "A user identity is required for a user-scoped MCP read.",
                )
            session = user_sessions.get((body.user_id, body.project_id))
            if session is None or (session.expires_at and session.expires_at <= datetime.now(UTC)):
                raise HTTPException(
                    status.HTTP_401_UNAUTHORIZED,
                    "No active user-scoped Atlassian MCP session is available.",
                )
            authorization = f"Bearer {session.access_token}"
            credential_fingerprint = session.access_token
        else:
            if body.user_id:
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_CONTENT,
                    "A service-identity read cannot impersonate a user.",
                )
            if configured.rovo_service_auth_mode == "BASIC" and configured.rovo_service_token:
                encoded = base64.b64encode(
                    f"{configured.rovo_service_username}:{configured.rovo_service_token}".encode()
                ).decode()
                authorization = f"Basic {encoded}"
            else:
                authorization = f"Bearer {configured.rovo_service_token}"
            credential_fingerprint = configured.rovo_service_token
        if not credential_fingerprint:
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "The requested Atlassian MCP identity is not configured.",
            )
        client_key = (
            f"user:{body.project_id}:{body.user_id}" if body.identity_class == "USER" else "service"
        )
        cached = mcp_clients.get(client_key)
        if cached is None or cached[0] != credential_fingerprint:
            cached = (
                credential_fingerprint,
                RovoMcpClient(configured.rovo_mcp_url, authorization, policy),
            )
            mcp_clients[client_key] = cached
        try:
            result = await cached[1].call_tool(body.tool, body.arguments)
        except Exception:
            MCP_CALLS.labels(body.identity_class, body.tool, "failed").inc()
            raise
        MCP_CALLS.labels(body.identity_class, body.tool, "succeeded").inc()
        content = result.get("content") if isinstance(result.get("content"), list) else []
        return McpResult(
            tool=body.tool, complete=bool(result.get("complete", False)), content=content
        )

    @app.put("/v1/internal/sessions")
    async def register_session(
        body: SessionRegistration, x_internal_api_key: Annotated[str | None, Header()] = None
    ):
        authorize_internal(x_internal_api_key, configured.internal_api_key)
        user_sessions[(body.user_id, body.project_id)] = body
        mcp_clients.pop(f"user:{body.project_id}:{body.user_id}", None)
        return {"registered": True, "identityClass": "USER", "expiresAt": body.expires_at}

    @app.delete("/v1/internal/sessions/{project_id}/{user_id}", status_code=204)
    async def delete_session(
        project_id: str, user_id: str, x_internal_api_key: Annotated[str | None, Header()] = None
    ):
        authorize_internal(x_internal_api_key, configured.internal_api_key)
        user_sessions.pop((user_id, project_id), None)
        mcp_clients.pop(f"user:{project_id}:{user_id}", None)

    @app.post("/v1/internal/mutations")
    async def mutation(
        _: MutationRequest, x_internal_api_key: Annotated[str | None, Header()] = None
    ):
        authorize_internal(x_internal_api_key, configured.internal_api_key)
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail={
                "code": "ATLASSIAN_WRITE_DISABLED",
                "message": "Atlassian write access is disabled.",
            },
        )

    @app.post("/v1/internal/rest-read")
    async def rest_read(
        body: RestReadRequest, x_internal_api_key: Annotated[str | None, Header()] = None
    ):
        authorize_internal(x_internal_api_key, configured.internal_api_key)
        headers = {"Accept": "*/*"}
        if configured.backend_internal_api_key:
            headers["Authorization"] = f"Bearer {configured.backend_internal_api_key}"
        query = [
            ("target", body.target),
            *((key, str(value)) for key, value in body.params.items()),
        ]
        async with httpx.AsyncClient(timeout=65.0) as client:
            response = await client.get(
                f"{configured.backend_url.rstrip('/')}/v1/internal/ingestion/projects/{quote(body.project_id, safe='')}/atlassian",
                headers=headers,
                params=query,
            )
        response.raise_for_status()
        return Response(
            content=response.content,
            media_type=response.headers.get("content-type", "application/octet-stream"),
            headers={"X-Atlassian-Transport": "REST_FALLBACK", "Cache-Control": "no-store"},
        )

    return app


app = create_app()
