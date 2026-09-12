"""Register the current ngrok HTTPS URL with the local service and Forge bridge."""

import json
import os
import urllib.request


def main() -> None:
    with urllib.request.urlopen("http://127.0.0.1:4040/api/tunnels", timeout=5) as response:
        tunnels = json.load(response).get("tunnels", [])
    public_url = next(
        (
            str(value.get("public_url"))
            for value in tunnels
            if str(value.get("public_url", "")).startswith("https://")
        ),
        "",
    )
    if not public_url:
        raise SystemExit("No ngrok HTTPS tunnel is running.")
    payload = json.dumps({"url": public_url}).encode()
    request = urllib.request.Request(
        "http://127.0.0.1:8005/v1/forge/callback",
        data=payload,
        method="PUT",
        headers={
            "content-type": "application/json",
            "X-Internal-Api-Key": os.environ["PI_ATLASSIAN_INTERNAL_API_KEY"],
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        if response.status != 200:
            raise SystemExit(f"Callback registration failed: {response.status}")
    print(public_url)


if __name__ == "__main__":
    main()
