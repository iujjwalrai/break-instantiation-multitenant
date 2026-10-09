from __future__ import annotations

import typing

from django.conf import settings
from rest_framework import exceptions
from rest_framework.authentication import BaseAuthentication
from rest_framework.authentication import CSRFCheck

from break_instantiation_backend.sessions import SessionExpiredError
from break_instantiation_backend.sessions import SessionInvalidError

from .services import resolve_client_session

if typing.TYPE_CHECKING:
    from rest_framework.request import Request

    from .models import ClientSession
    from .models import ClientUser


class ClientSessionAuthentication(BaseAuthentication):
    """Resolve the client session cookie. Not a default auth class.

    Wired per view. A missing cookie is not a failure. A bad cookie is.
    """

    def authenticate(
        self,
        request: Request,
    ) -> tuple[ClientUser, ClientSession] | None:
        raw_token = request.COOKIES.get(settings.CLIENT_SESSION_COOKIE_NAME)
        if not raw_token:
            return None
        self.enforce_csrf(request)
        try:
            session = resolve_client_session(raw_token)
        except (SessionInvalidError, SessionExpiredError) as exc:
            raise exceptions.AuthenticationFailed(str(exc)) from exc
        return session.client_user, session

    def enforce_csrf(self, request: Request) -> None:
        """The cookie is sent automatically, so CSRF is mandatory here."""

        def dummy_get_response(request: Request) -> None:  # pragma: no cover
            return None

        check = CSRFCheck(dummy_get_response)  # type: ignore[arg-type]
        check.process_request(request)
        reason = check.process_view(request, None, (), {})  # type: ignore[arg-type]
        if reason:
            msg = f"CSRF Failed: {reason}"
            raise exceptions.PermissionDenied(msg)
