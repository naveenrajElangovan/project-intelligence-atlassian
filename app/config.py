from functools import lru_cache
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    environment: str = "development"
    access_mode: Literal["READ_ONLY", "READ_WRITE"] = "READ_ONLY"
    write_enabled: bool = False
    internal_api_key: str = ""
    forge_webhook_secret: str = ""
    forge_config_url: str = ""
    forge_config_secret: str = ""
    rovo_mcp_url: str = "https://mcp.atlassian.com/v2/mcp?tools=all"
    rovo_service_auth_mode: Literal["BEARER", "BASIC"] = "BEARER"
    rovo_service_username: str = ""
    rovo_service_token: str = ""
    backend_url: str = "http://api:8000"
    backend_internal_api_key: str = ""
    ingestion_url: str = "http://ingestion:8000"
    ingestion_internal_api_key: str = ""
    application_projects: str = ""
    event_max_bytes: int = Field(default=262_144, ge=1024, le=2_097_152)
    event_max_age_seconds: int = Field(default=300, ge=30, le=900)
    event_debounce_seconds: float = Field(default=2.0, ge=0.0, le=30.0)
    dispatch_retry_attempts: int = Field(default=3, ge=1, le=8)
    project_catalog_ttl_seconds: int = Field(default=30, ge=1, le=300)
    recovery_scan_seconds: int = Field(default=300, ge=60, le=86_400)
    catch_up_timeout_seconds: int = Field(default=1800, ge=60, le=7200)

    model_config = SettingsConfigDict(
        env_prefix="PI_ATLASSIAN_", env_file=".env", extra="ignore"
    )

    @model_validator(mode="after")
    def enforce_initial_read_only_release(self):
        if self.access_mode != "READ_ONLY" or self.write_enabled:
            raise ValueError("The initial Atlassian service release is read-only.")
        if self.rovo_service_token and self.rovo_service_auth_mode == "BASIC" and not self.rovo_service_username:
            raise ValueError("A Rovo username is required for BASIC service authentication.")
        return self

    @property
    def application_project_ids(self) -> tuple[str, ...]:
        return tuple(
            dict.fromkeys(
                value.strip() for value in self.application_projects.split(",") if value.strip()
            )
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
