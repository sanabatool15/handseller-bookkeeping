"""Deep-link generation utility for surfacing agent insights back into the app UI."""
from __future__ import annotations

from urllib.parse import urlencode

APP_BASE_URL = "https://app.handseller.example"


def build_deep_link(*, org_id: str, resource: str, resource_id: str | None = None, **query_params: str) -> str:
    """Builds a client-side deep link, e.g. build_deep_link(org_id=..., resource="sales", resource_id=...)."""
    path = f"/orgs/{org_id}/{resource}"
    if resource_id:
        path += f"/{resource_id}"
    query = urlencode(query_params)
    return f"{APP_BASE_URL}{path}" + (f"?{query}" if query else "")
