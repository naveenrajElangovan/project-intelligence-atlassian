from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ResourceType(StrEnum):
    ISSUE = "ISSUE"
    COMMENT = "COMMENT"
    WORKLOG = "WORKLOG"
    ISSUE_LINK = "ISSUE_LINK"
    ATTACHMENT = "ATTACHMENT"
    PAGE = "PAGE"
    LIVE_DOCUMENT = "LIVE_DOCUMENT"
    BLOGPOST = "BLOGPOST"


class AtlassianEvent(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    event_id: str = Field(alias="eventId", min_length=1, max_length=256)
    event_type: str = Field(alias="eventType", min_length=1, max_length=160)
    event_created_at: datetime = Field(alias="eventCreatedAt")
    cloud_id: str = Field(alias="cloudId", min_length=1, max_length=128)
    resource_type: ResourceType = Field(alias="resourceType")
    resource_id: str = Field(alias="resourceId", min_length=1, max_length=128)
    parent_resource_id: str | None = Field(default=None, alias="parentResourceId", max_length=128)
    project_or_space_id: str = Field(alias="projectOrSpaceId", min_length=1, max_length=128)
    application_project_id: str | None = Field(
        default=None, alias="applicationProjectId", min_length=1, max_length=128
    )
    self_generated: bool = Field(default=False, alias="selfGenerated")

    @property
    def parent_identity(self) -> str:
        return self.parent_resource_id or self.resource_id


class EventAcceptance(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    accepted: bool
    duplicate: bool = False
    reason: str
    event_id: str = Field(alias="eventId")


class SearchRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    project_id: str = Field(alias="projectId", min_length=1, max_length=128)
    query: str = Field(min_length=1, max_length=4096)
    tool: str = Field(default="search", min_length=1, max_length=128)
    arguments: dict[str, Any] = Field(default_factory=dict)
    user_id: str | None = Field(default=None, alias="userId", max_length=128)
    identity_class: Literal["SERVICE", "USER"] = Field(default="SERVICE", alias="identityClass")


class SessionRegistration(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    user_id: str = Field(alias="userId", min_length=1, max_length=128)
    project_id: str = Field(alias="projectId", min_length=1, max_length=128)
    access_token: str = Field(alias="accessToken", min_length=20, max_length=8192)
    expires_at: datetime | None = Field(default=None, alias="expiresAt")


class McpResult(BaseModel):
    tool: str
    transport: str = "ROVO_MCP"
    complete: bool
    content: list[dict[str, Any]]


class MutationRequest(BaseModel):
    operation: str = Field(min_length=1, max_length=128)
    arguments: dict[str, Any] = Field(default_factory=dict)


class RestReadRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    project_id: str = Field(alias="projectId", min_length=1, max_length=128)
    target: str = Field(min_length=1, max_length=4096)
    params: dict[str, str | int] = Field(default_factory=dict)


class CallbackRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    url: str = Field(pattern=r"^https://[A-Za-z0-9.-]+(?::\d+)?(?:/.*)?$")
