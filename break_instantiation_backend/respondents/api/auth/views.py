from __future__ import annotations

import typing
from urllib.parse import urlsplit

from django.conf import settings
from django.middleware.csrf import get_token
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle
from rest_framework.views import APIView

from break_instantiation_backend.respondents.authentication import (
    RespondentSessionAuthentication,
)
from break_instantiation_backend.respondents.models import Respondent
from break_instantiation_backend.respondents.services import issue_magic_login
from break_instantiation_backend.respondents.services import redeem_magic_login
from break_instantiation_backend.respondents.services import (
    revoke_all_respondent_sessions,
)
from break_instantiation_backend.respondents.services import revoke_respondent_session
from break_instantiation_backend.respondents.tasks import send_magic_login_email
from break_instantiation_backend.throttling import EmailRateThrottle
from break_instantiation_backend.tokens import TokenExpiredError
from break_instantiation_backend.tokens import TokenInvalidError

from .serializers import MagicLoginRedeemSerializer
from .serializers import MagicLoginRequestSerializer

if typing.TYPE_CHECKING:
    from rest_framework.request import Request

_GENERIC_MAGIC_LOGIN_RESPONSE = {
    "detail": "If an account exists, a sign-in link has been sent.",
}


def _caller_origin(request: Request) -> str | None:
    """Page that sent the request, not this API's own host.

    The browser `Origin` is the child address (`http://localhost:5173` in
    the playground). A proxy rewrites `Host` to Django, so the link must
    not be built from `Host`.
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


def _token_error_response(exc: TokenInvalidError | TokenExpiredError) -> Response:
    status_code = (
        status.HTTP_410_GONE
        if isinstance(exc, TokenExpiredError)
        else status.HTTP_400_BAD_REQUEST
    )
    return Response({"detail": str(exc)}, status=status_code)


def _set_respondent_session_cookie(
    response: Response,
    raw_token: str,
    request: Request,
) -> None:
    """No max_age: a fixed lifetime would ignore the sliding idle window."""
    response.set_cookie(
        settings.RESPONDENT_SESSION_COOKIE_NAME,
        raw_token,
        httponly=True,
        secure=not settings.DEBUG,
        samesite="Lax",
    )
    get_token(request)


class MagicLoginRequestThrottle(EmailRateThrottle):
    scope = "magic_login"


class MagicLoginRequestIPThrottle(AnonRateThrottle):
    """One IP spraying many emails. The per-email throttle does not catch that."""

    scope = "magic_login_ip"


class MagicLoginRequestView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [MagicLoginRequestThrottle, MagicLoginRequestIPThrottle]

    def post(self, request: Request) -> Response:
        serializer = MagicLoginRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data["email"]

        respondent = Respondent.objects.filter(
            email__iexact=email,
            disabled_at__isnull=True,
        ).first()
        if respondent is not None:
            origin = _caller_origin(request)
            if origin is not None:
                _token, raw_token = issue_magic_login(respondent=respondent)
                send_magic_login_email.delay(respondent.email, raw_token, origin)

        return Response(_GENERIC_MAGIC_LOGIN_RESPONSE)


class MagicLoginRedeemView(APIView):
    permission_classes = [AllowAny]

    def post(self, request: Request) -> Response:
        serializer = MagicLoginRedeemSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        token = serializer.validated_data["token"]

        try:
            respondent, _session, raw_session_token = redeem_magic_login(token)
        except (TokenInvalidError, TokenExpiredError) as exc:
            return _token_error_response(exc)

        response = Response({"email": respondent.email})
        _set_respondent_session_cookie(response, raw_session_token, request)
        return response


class RespondentLogoutView(APIView):
    authentication_classes = [RespondentSessionAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request: Request) -> Response:
        raw_token = request.COOKIES.get(settings.RESPONDENT_SESSION_COOKIE_NAME)
        assert raw_token is not None, (
            "authentication requires this cookie to be present"
        )
        revoke_respondent_session(raw_token)
        response = Response(status=status.HTTP_204_NO_CONTENT)
        response.delete_cookie(settings.RESPONDENT_SESSION_COOKIE_NAME)
        return response


class RespondentLogoutAllView(APIView):
    authentication_classes = [RespondentSessionAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request: Request) -> Response:
        assert isinstance(request.user, Respondent)
        revoke_all_respondent_sessions(request.user)
        response = Response(status=status.HTTP_204_NO_CONTENT)
        response.delete_cookie(settings.RESPONDENT_SESSION_COOKIE_NAME)
        return response
