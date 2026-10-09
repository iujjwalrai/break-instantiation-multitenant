from __future__ import annotations

import typing
from urllib.parse import urlsplit

if typing.TYPE_CHECKING:
    from rest_framework.request import Request


def caller_origin(request: Request) -> str | None:
    """Page that sent the request, not this API's own host.

    The browser `Origin` is the child address. A proxy rewrites `Host`
    to Django, so links must not be built from `Host`.
    """
    raw = request.headers.get("Origin", "")
    parts = urlsplit(raw)
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        return None
    if parts.username or parts.password or parts.path not in {"", "/"}:
        return None
    if parts.query or parts.fragment:
        return None
    return f"{parts.scheme}://{parts.netloc}"
