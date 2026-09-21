import hashlib
import hmac
import time

import pytest
from fastapi import HTTPException

from app.security import ReadOnlyToolPolicy, verify_forge_signature


@pytest.mark.parametrize(
    "tool",
    [
        "search",
        "searchJiraIssuesUsingJql",
        "getConfluenceComment",
        "listJiraIssueComments",
        "executeRead",
        "discover",
    ],
)
def test_read_tools_allowed(tool):
    ReadOnlyToolPolicy().authorize(tool)


@pytest.mark.parametrize(
    "tool",
    [
        "createIssue",
        "update_page",
        "delete-comment",
        "transitionIssue",
        "uploadAttachment",
        "searchAndMutate",
        "getAndSetPermissions",
        "execute",
    ],
)
def test_write_and_unknown_tools_blocked(tool):
    with pytest.raises(HTTPException) as raised:
        ReadOnlyToolPolicy().authorize(tool)
    assert raised.value.status_code == 403
    assert raised.value.detail["code"] == "ATLASSIAN_WRITE_DISABLED"


def test_signature_validation():
    body = b'{"eventId":"one"}'
    timestamp = str(int(time.time()))
    signature = (
        "sha256="
        + hmac.new(b"secret", timestamp.encode() + b"." + body, hashlib.sha256).hexdigest()
    )
    verify_forge_signature(body, signature, timestamp, "secret", 300)


def test_bad_signature_rejected():
    with pytest.raises(HTTPException) as raised:
        verify_forge_signature(b"{}", "sha256=no", str(int(time.time())), "secret", 300)
    assert raised.value.status_code == 401
