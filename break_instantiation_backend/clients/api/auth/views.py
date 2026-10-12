from __future__ import annotations

import typing

from django.conf import settings
from django.middleware.csrf import get_token
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle
from rest_framework.views import APIView

from break_instantiation_backend.clients.authentication import (
    ClientSessionAuthentication,
)
from break_instantiation_backend.clients.models import ClientUser
from break_instantiation_backend.clients.services import issue_magic_login
from break_instantiation_backend.clients.services import redeem_magic_login
from break_instantiation_backend.clients.services import redeem_portal_invite
from break_instantiation_backend.clients.services import revoke_all_client_sessions
from break_instantiation_backend.clients.services import revoke_client_session
from break_instantiation_backend.clients.services import verify_portal_invite
from break_instantiation_backend.clients.tasks import send_magic_login_email
from break_instantiation_backend.throttling import EmailRateThrottle
from break_instantiation_backend.tokens import TokenExpiredError
from break_instantiation_backend.tokens import TokenInvalidError

from .serializers import MagicLoginRedeemSerializer
from .serializers import MagicLoginRequestSerializer
from .serializers import PortalInviteRedeemSerializer

if typing.TYPE_CHECKING:
    from rest_framework.request import Request

_GENERIC_MAGIC_LOGIN_RESPONSE = {
    "detail": "If an account exists, a sign-in link has been sent.",
}


def _token_error_response(exc: TokenInvalidError | TokenExpiredError) -> Response:
    status_code = (
        status.HTTP_410_GONE
        if isinstance(exc, TokenExpiredError)
        else status.HTTP_400_BAD_REQUEST
    )
    return Response({"detail": str(exc)}, status=status_code)


def _set_client_session_cookie(
    response: Response,
    raw_token: str,
    request: Request,
) -> None:
    """No max_age: a fixed lifetime would ignore the sliding idle window."""
    response.set_cookie(
        settings.CLIENT_SESSION_COOKIE_NAME,
        raw_token,
        httponly=True,
        secure=not settings.DEBUG,
        samesite="Lax",
    )
    get_token(request)


class PortalInviteVerifyView(APIView):
    permission_classes = [AllowAny]

    def get(self, request: Request) -> Response:
        token = request.query_params.get("token", "")
        if not token:
            return Response(
                {"detail": "Token is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            invite = verify_portal_invite(token)
        except (TokenInvalidError, TokenExpiredError) as exc:
            return _token_error_response(exc)
        return Response({"email": invite.invited_email})


class PortalInviteRedeemView(APIView):
    permission_classes = [AllowAny]

    def post(self, request: Request) -> Response:
        serializer = PortalInviteRedeemSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        token = serializer.validated_data["token"]

        try:
            client_user, _session, raw_session_token = redeem_portal_invite(token)
        except (TokenInvalidError, TokenExpiredError) as exc:
            return _token_error_response(exc)

        response = Response({"email": client_user.email})
        _set_client_session_cookie(response, raw_session_token, request)
        return response


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

        client_user = ClientUser.objects.filter(
            email__iexact=email,
            disabled_at__isnull=True,
        ).first()
        if client_user is not None:
            _token, raw_token = issue_magic_login(client_user=client_user)
            send_magic_login_email.delay(client_user.email, raw_token)

        return Response(_GENERIC_MAGIC_LOGIN_RESPONSE)


class MagicLoginRedeemView(APIView):
    permission_classes = [AllowAny]

    def post(self, request: Request) -> Response:
        serializer = MagicLoginRedeemSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        token = serializer.validated_data["token"]

        try:
            client_user, _session, raw_session_token = redeem_magic_login(token)
        except (TokenInvalidError, TokenExpiredError) as exc:
            return _token_error_response(exc)

        response = Response({"email": client_user.email})
        _set_client_session_cookie(response, raw_session_token, request)
        return response


class PortalLogoutView(APIView):
    authentication_classes = [ClientSessionAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request: Request) -> Response:
        raw_token = request.COOKIES.get(settings.CLIENT_SESSION_COOKIE_NAME)
        assert raw_token is not None, (
            "authentication requires this cookie to be present"
        )
        revoke_client_session(raw_token)
        response = Response(status=status.HTTP_204_NO_CONTENT)
        response.delete_cookie(settings.CLIENT_SESSION_COOKIE_NAME)
        return response


class PortalLogoutAllView(APIView):
    authentication_classes = [ClientSessionAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request: Request) -> Response:
        assert isinstance(request.user, ClientUser)
        revoke_all_client_sessions(request.user)
        response = Response(status=status.HTTP_204_NO_CONTENT)
        response.delete_cookie(settings.CLIENT_SESSION_COOKIE_NAME)
        return response
