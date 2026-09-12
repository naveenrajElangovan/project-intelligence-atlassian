import asyncio
import time
from collections import OrderedDict
from typing import Any

import httpx

from app.config import Settings
from app.models import AtlassianEvent
from app.telemetry import CATCH_UP_SECONDS, DISPATCH_SECONDS, PENDING


class EventCoordinator:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.queue: asyncio.Queue[AtlassianEvent] = asyncio.Queue(maxsize=1000)
        self.seen: OrderedDict[str, float] = OrderedDict()
        self.pending: dict[str, AtlassianEvent] = {}
        self.worker: asyncio.Task | None = None
        self.last_success_at: float | None = None
        self.last_failure: str | None = None
        self.freshness_by_scope: dict[str, dict[str, Any]] = {}
        self._project_catalog: tuple[dict[str, Any], ...] = ()
        self._project_catalog_loaded_at = 0.0

    async def start(self) -> None:
        if self.worker is None:
            self.worker = asyncio.create_task(self._consume())

    async def stop(self) -> None:
        if self.worker:
            self.worker.cancel()
            try:
                await self.worker
            except asyncio.CancelledError:
                pass
            self.worker = None

    async def catch_up(self) -> None:
        began = time.monotonic()
        headers = {"X-Internal-Api-Key": self.settings.ingestion_internal_api_key}
        try:
            configured = set(self.settings.application_project_ids)
            projects = tuple(
                item
                for item in await self._projects()
                if item.get("projectId")
                and (not configured or str(item.get("projectId")) in configured)
            )
        except Exception as error:  # noqa: BLE001 - discovery failures must not stop recovery
            self.last_failure = f"project_discovery:{type(error).__name__}"
            CATCH_UP_SECONDS.labels("failed").observe(time.monotonic() - began)
            return
        if not projects:
            self.last_failure = "project_discovery:no_authorized_projects"
            CATCH_UP_SECONDS.labels("failed").observe(time.monotonic() - began)
            return
        failures: list[str] = []
        in_progress = False
        async with httpx.AsyncClient(timeout=self.settings.catch_up_timeout_seconds) as client:
            for project in projects:
                project_id = str(project["projectId"])
                providers = tuple(
                    provider
                    for provider, mapping_key in (
                        ("JIRA", "jiraProjects"),
                        ("CONFLUENCE", "confluenceSpaces"),
                    )
                    if project.get(mapping_key)
                )
                for provider in providers:
                    scope_key = f"{project_id}:{provider}"
                    try:
                        response = await client.post(
                            f"{self.settings.ingestion_url.rstrip('/')}/v1/projects/{project_id}/ingestions",
                            headers=headers,
                            json={"providers": [provider], "full": False},
                        )
                        if response.status_code == 409:
                            in_progress = True
                            self.freshness_by_scope[scope_key] = {
                                **self.freshness_by_scope.get(scope_key, {}),
                                "state": "IN_PROGRESS",
                            }
                            continue
                        response.raise_for_status()
                        completed_at = time.time()
                        self.freshness_by_scope[scope_key] = {
                            "state": "FRESH",
                            "lastCompletedAt": completed_at,
                            "lastFailure": None,
                        }
                    except Exception as error:  # noqa: BLE001 - record per-project recovery failure
                        failure = type(error).__name__
                        self.freshness_by_scope[scope_key] = {
                            **self.freshness_by_scope.get(scope_key, {}),
                            "state": "FAILED",
                            "lastFailure": failure,
                        }
                        failures.append(f"{scope_key}:{failure}")
        if failures:
            self.last_failure = "catch_up:" + ",".join(failures)
            CATCH_UP_SECONDS.labels("failed").observe(time.monotonic() - began)
            return
        if in_progress:
            self.last_failure = "catch_up:in_progress"
            CATCH_UP_SECONDS.labels("in_progress").observe(time.monotonic() - began)
            return
        self.last_success_at = time.time()
        self.last_failure = None
        CATCH_UP_SECONDS.labels("succeeded").observe(time.monotonic() - began)

    async def recovery_loop(self) -> None:
        while True:
            try:
                await self.catch_up()
            except asyncio.CancelledError:
                raise
            except Exception as error:  # noqa: BLE001 - worker must survive one bad scan
                self.last_failure = f"recovery_loop:{type(error).__name__}"
            await asyncio.sleep(self.settings.recovery_scan_seconds)

    async def accept(self, event: AtlassianEvent) -> bool:
        now = time.monotonic()
        while self.seen and next(iter(self.seen.values())) < now - 3600:
            self.seen.popitem(last=False)
        if event.event_id in self.seen:
            return False
        self.seen[event.event_id] = now
        await self.queue.put(event)
        PENDING.set(self.queue.qsize() + len(self.pending))
        return True

    async def _consume(self) -> None:
        while True:
            event = await self.queue.get()
            key = f"{event.cloud_id}:{event.parent_identity}"
            self.pending[key] = event
            await asyncio.sleep(self.settings.event_debounce_seconds)
            selected = self.pending.pop(key, None)
            if selected is None:
                self.queue.task_done()
                continue
            try:
                await self._dispatch_with_retry(selected)
                self.last_success_at = time.time()
                self.last_failure = None
            except Exception as error:  # noqa: BLE001 - event failures are retried/recovered
                self.last_failure = type(error).__name__
            finally:
                self.queue.task_done()
                PENDING.set(self.queue.qsize() + len(self.pending))

    async def _dispatch_with_retry(self, event: AtlassianEvent) -> None:
        for attempt in range(self.settings.dispatch_retry_attempts):
            try:
                await self._dispatch(event)
                return
            except (httpx.TransportError, httpx.HTTPStatusError):
                if attempt + 1 >= self.settings.dispatch_retry_attempts:
                    raise
                await asyncio.sleep(min(8.0, 2.0**attempt))

    async def _dispatch(self, event: AtlassianEvent) -> None:
        provider = "JIRA" if event.event_type.startswith(("avi:jira:", "jira:")) else "CONFLUENCE"
        began = time.monotonic()
        body = {
            "provider": provider,
            "cloudId": event.cloud_id,
            "resourceType": event.resource_type.value,
            "resourceId": event.parent_identity,
            "childResourceId": event.resource_id if event.parent_resource_id else None,
            "projectOrSpaceId": event.project_or_space_id,
            "eventType": event.event_type,
            "deleted": (
                "deleted" in event.event_type.lower()
                and event.resource_type.value in {"ISSUE", "PAGE", "LIVE_DOCUMENT", "BLOGPOST"}
            ),
            "childDeleted": (
                "deleted" in event.event_type.lower()
                and event.parent_resource_id is not None
            ),
        }
        try:
            projects = await self._resolve_projects(event, provider)
            if not projects:
                raise RuntimeError("Atlassian event does not match an authorized project mapping")
            headers = {"X-Internal-Api-Key": self.settings.ingestion_internal_api_key}
            async with httpx.AsyncClient(timeout=120.0) as client:
                for project_id in projects:
                    url = f"{self.settings.ingestion_url.rstrip('/')}/v1/projects/{project_id}/ingestions/targeted"
                    response = await client.post(url, headers=headers, json=body)
                    response.raise_for_status()
        except Exception:
            DISPATCH_SECONDS.labels(provider, "failed").observe(time.monotonic() - began)
            raise
        DISPATCH_SECONDS.labels(provider, "succeeded").observe(time.monotonic() - began)

    async def _resolve_projects(self, event: AtlassianEvent, provider: str) -> tuple[str, ...]:
        matches: list[str] = []
        cloud_candidates: list[str] = []
        for project in await self._projects():
            project_id = str(project.get("projectId") or "")
            gateway = project.get("atlassian")
            if not project_id or not isinstance(gateway, dict):
                continue
            if str(gateway.get("cloudId") or "") != event.cloud_id:
                continue
            cloud_candidates.append(project_id)
            mappings = project.get("jiraProjects" if provider == "JIRA" else "confluenceSpaces")
            if not isinstance(mappings, list):
                continue
            key = "projectKey" if provider == "JIRA" else "spaceId"
            if any(
                isinstance(item, dict)
                and str(item.get(key) or "") == event.project_or_space_id
                for item in mappings
            ):
                matches.append(project_id)
        if not matches and provider == "JIRA" and event.project_or_space_id.isdigit():
            # Jira issue-link events carry a numeric Jira project ID. Resolve it
            # only when the cloud maps to exactly one application project; a
            # multi-project cloud must wait for the recovery scan rather than guess.
            unique = tuple(dict.fromkeys(cloud_candidates))
            if len(unique) == 1:
                matches.extend(unique)
        if event.application_project_id:
            return (event.application_project_id,) if event.application_project_id in matches else ()
        return tuple(dict.fromkeys(matches))

    async def _projects(self) -> tuple[dict[str, Any], ...]:
        now = time.monotonic()
        if self._project_catalog and now - self._project_catalog_loaded_at < self.settings.project_catalog_ttl_seconds:
            return self._project_catalog
        headers = {"Accept": "application/json"}
        if self.settings.backend_internal_api_key:
            headers["Authorization"] = f"Bearer {self.settings.backend_internal_api_key}"
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.get(
                f"{self.settings.backend_url.rstrip('/')}/v1/internal/ingestion/projects",
                headers=headers,
            )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, list):
            raise TypeError("Backend returned an invalid project catalog")
        self._project_catalog = tuple(item for item in payload if isinstance(item, dict))
        self._project_catalog_loaded_at = now
        return self._project_catalog
