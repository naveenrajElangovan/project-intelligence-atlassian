import hashlib
import hmac
import re
import time

from fastapi import HTTPException, status

_WRITE_MARKERS = {
    "add",
    "archive",
    "assign",
    "create",
    "delete",
    "edit",
    "move",
    "mutate",
    "patch",
    "publish",
    "remove",
    "restore",
    "set",
    "transition",
    "update",
    "upload",
    "write",
}
_READ_PREFIXES = (
    "atlassian_user_info",
    "discover",
    "download_",
    "execute_read",
    "export_",
    "fetch_",
    "find_",
    "get_",
    "list_",
    "lookup_",
    "read_",
    "resolve_",
    "search",
)


class ReadOnlyToolPolicy:
    def authorize(self, tool: str) -> None:
        normalized = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", tool).lower().replace("-", "_")
        parts = {part for part in normalized.split("_") if part}
        if parts & _WRITE_MARKERS or not normalized.startswith(_READ_PREFIXES):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                detail={
                    "code": "ATLASSIAN_WRITE_DISABLED",
                    "message": "Only read operations are enabled.",
                },
            )


def verify_forge_signature(
    body: bytes, signature: str | None, timestamp: str | None, secret: str, max_age: int
) -> None:
    if not secret:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "Forge webhook secret is not configured."
        )
    if not signature or not timestamp:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing Forge signature headers.")
    try:
        sent_at = int(timestamp)
    except ValueError as error:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid Forge timestamp.") from error
    if abs(int(time.time()) - sent_at) > max_age:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Expired Forge event.")
    expected = (
        "sha256="
        + hmac.new(secret.encode(), timestamp.encode() + b"." + body, hashlib.sha256).hexdigest()
    )
    if not hmac.compare_digest(expected, signature):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid Forge signature.")


def authorize_internal(supplied: str | None, expected: str) -> None:
    if not expected or not supplied or not hmac.compare_digest(supplied, expected):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid internal API key.")
