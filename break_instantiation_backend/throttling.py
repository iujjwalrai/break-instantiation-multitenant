from __future__ import annotations

import typing

from rest_framework.throttling import SimpleRateThrottle

if typing.TYPE_CHECKING:
    from rest_framework.request import Request
    from rest_framework.views import APIView


class EmailRateThrottle(SimpleRateThrottle):
    """Rate-limit by the `email` field in the body, not by IP.

    Stops one inbox being hammered from many addresses. An IP throttle does
    not. Subclasses set `scope` so each endpoint has its own bucket.
    """

    def get_cache_key(self, request: Request, view: APIView) -> str | None:
        email = str(request.data.get("email", "")).strip().lower()
        if not email:
            return None
        return self.cache_format % {"scope": self.scope, "ident": email}
