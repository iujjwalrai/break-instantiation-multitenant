from __future__ import annotations

import typing

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from break_instantiation_backend.audit.models import AuthEventType
from break_instantiation_backend.audit.services import record_event
from break_instantiation_backend.sessions import SessionExpiredError
from break_instantiation_backend.sessions import SessionInvalidError
from break_instantiation_backend.tokens import TokenExpiredError
from break_instantiation_backend.tokens import TokenInvalidError
from break_instantiation_backend.tokens import expire_unused
from break_instantiation_backend.tokens import generate_token
from break_instantiation_backend.tokens import hash_token
from break_instantiation_backend.tokens import redeem
from break_instantiation_backend.tokens import verify
from break_instantiation_backend.users.staff_auth import CrossSchemaInviteError
from break_instantiation_backend.users.staff_auth import user_in_current_schema

from .models import Client
from .models import ClientPortalInvite
from .models import ClientSession
from .models import ClientUser
from .models import MagicLoginToken

if typing.TYPE_CHECKING:
    from datetime import timedelta

    from django.http import HttpRequest

    from break_instantiation_backend.users.models import User


def issue_portal_invite(
    *,
    target_client: Client,
    invited_by: User,
    request: HttpRequest | None = None,
    ttl: timedelta | None = None,
) -> tuple[ClientPortalInvite, str]:
    """Create an invite and hard-expire older unused ones for this client.

    Records `INVITE_SENT` against the staff sender. No `ClientUser` exists
    yet, and an auth event needs exactly one identity.
    """
    if not user_in_current_schema(invited_by):
        msg = "A customer admin in this company sends the invite."
        raise CrossSchemaInviteError(msg)
    raw_token = generate_token()
    with transaction.atomic():
        expire_unused(
            ClientPortalInvite.objects.filter(target_client=target_client),
        )
        invite = ClientPortalInvite.objects.create(
            invited_email=target_client.email,
            invited_by=invited_by,
            target_client=target_client,
            token_hash=hash_token(raw_token),
            expires_at=timezone.now() + (ttl or settings.CLIENT_PORTAL_INVITE_TTL),
        )
        record_event(AuthEventType.INVITE_SENT, user=invited_by, request=request)
    return invite, raw_token


def verify_portal_invite(raw_token: str) -> ClientPortalInvite:
    """Look up an invite without consuming it. Stamps `opened_at` once."""
    invite = verify(ClientPortalInvite, raw_token)
    if invite.opened_at is None:
        invite.opened_at = timezone.now()
        invite.save(update_fields=["opened_at", "modified"])
    return invite


def redeem_portal_invite(
    raw_token: str,
    *,
    request: HttpRequest | None = None,
) -> tuple[ClientUser, ClientSession, str]:
    """Consume an invite, create the `ClientUser`, and start a session.

    `INVITE_REDEEMED` and the session's `LOGIN_SUCCESS` are both recorded.
    """
    with transaction.atomic():
        invite = redeem(ClientPortalInvite, raw_token)
        client_user, _created = ClientUser.objects.get_or_create(
            email=invite.invited_email,
        )
        if client_user.disabled_at is not None:
            msg = "This account has been disabled."
            raise TokenInvalidError(msg)
        client = invite.target_client
        if client.client_user_id != client_user.id:
            if (
                Client.objects.filter(client_user=client_user)
                .exclude(pk=client.pk)
                .exists()
            ):
                msg = "This email is already linked to a different client."
                raise TokenInvalidError(msg)
            previous_client_user_id = client.client_user_id
            client.client_user = client_user
            client.save(update_fields=["client_user", "modified"])
            if previous_client_user_id is not None:
                revoke_all_client_sessions(
                    ClientUser.objects.get(pk=previous_client_user_id),
                    request=request,
                )
        record_event(
            AuthEventType.INVITE_REDEEMED,
            client_user=client_user,
            request=request,
        )
        session, raw_session_token = issue_client_session(
            client_user=client_user,
            request=request,
        )
    return client_user, session, raw_session_token


def issue_magic_login(
    *,
    client_user: ClientUser,
    request: HttpRequest | None = None,
    ttl: timedelta | None = None,
) -> tuple[MagicLoginToken, str]:
    """Create a magic-login token and hard-expire older unused ones."""
    raw_token = generate_token()
    with transaction.atomic():
        expire_unused(MagicLoginToken.objects.filter(client_user=client_user))
        token = MagicLoginToken.objects.create(
            client_user=client_user,
            token_hash=hash_token(raw_token),
            expires_at=timezone.now() + (ttl or settings.MAGIC_LOGIN_TOKEN_TTL),
        )
        record_event(
            AuthEventType.MAGIC_LINK_SENT,
            client_user=client_user,
            request=request,
        )
    return token, raw_token


def redeem_magic_login(
    raw_token: str,
    *,
    request: HttpRequest | None = None,
) -> tuple[ClientUser, ClientSession, str]:
    """Consume a magic-login token and start a session.

    The session records `LOGIN_SUCCESS`. An expired token records
    `MAGIC_LINK_EXPIRED` and re-raises. Callers must catch
    `TokenExpiredError` and return a response: under `ATOMIC_REQUESTS`
    a propagating exception rolls the audit row back.
    """
    try:
        with transaction.atomic():
            token = redeem(MagicLoginToken, raw_token)
            if token.client_user.disabled_at is not None:
                msg = "This account has been disabled."
                raise TokenInvalidError(msg)
            session, raw_session_token = issue_client_session(
                client_user=token.client_user,
                request=request,
            )
    except TokenExpiredError:
        expired_token = MagicLoginToken.objects.get(token_hash=hash_token(raw_token))
        record_event(
            AuthEventType.MAGIC_LINK_EXPIRED,
            client_user=expired_token.client_user,
            request=request,
        )
        raise
    return token.client_user, session, raw_session_token


def issue_client_session(
    *,
    client_user: ClientUser,
    request: HttpRequest | None = None,
) -> tuple[ClientSession, str]:
    """Open a session. Does not revoke sessions this client already holds."""
    raw_token = generate_token()
    now = timezone.now()
    with transaction.atomic():
        session = ClientSession.objects.create(
            client_user=client_user,
            token_hash=hash_token(raw_token),
            expires_at=now + settings.CLIENT_SESSION_IDLE_TTL,
            last_used_at=now,
        )
        record_event(
            AuthEventType.LOGIN_SUCCESS,
            client_user=client_user,
            request=request,
        )
    return session, raw_token


def resolve_client_session(raw_token: str) -> ClientSession:
    """Look up an active session and slide its idle window when due."""
    try:
        session = ClientSession.objects.select_related("client_user").get(
            token_hash=hash_token(raw_token),
        )
    except ClientSession.DoesNotExist as exc:
        msg = "Session not found."
        raise SessionInvalidError(msg) from exc
    if session.revoked_at is not None:
        msg = "Session has been revoked."
        raise SessionInvalidError(msg)
    if session.client_user.disabled_at is not None:
        msg = "Client user is disabled."
        raise SessionInvalidError(msg)
    now = timezone.now()
    if session.expires_at <= now:
        msg = "Session has expired."
        raise SessionExpiredError(msg)
    if now - session.last_used_at > settings.SESSION_SLIDE_THRESHOLD:
        session.last_used_at = now
        session.expires_at = now + settings.CLIENT_SESSION_IDLE_TTL
        session.save(update_fields=["last_used_at", "expires_at", "modified"])
    return session


def revoke_client_session(
    raw_token: str,
    *,
    request: HttpRequest | None = None,
) -> None:
    """Revoke the session for this device. A second logout is a no-op."""
    try:
        session = ClientSession.objects.get(token_hash=hash_token(raw_token))
    except ClientSession.DoesNotExist as exc:
        msg = "Session not found."
        raise SessionInvalidError(msg) from exc
    if session.revoked_at is not None:
        return
    with transaction.atomic():
        session.revoked_at = timezone.now()
        session.save(update_fields=["revoked_at", "modified"])
        record_event(
            AuthEventType.LOGOUT,
            client_user=session.client_user,
            request=request,
        )


def revoke_all_client_sessions(
    client_user: ClientUser,
    *,
    request: HttpRequest | None = None,
) -> int:
    """Revoke every live session for `client_user`. One logout event."""
    with transaction.atomic():
        count = ClientSession.objects.filter(
            client_user=client_user,
            revoked_at__isnull=True,
        ).update(revoked_at=timezone.now())
        record_event(AuthEventType.LOGOUT, client_user=client_user, request=request)
    return count


def disable_client_user(
    client_user: ClientUser,
    *,
    request: HttpRequest | None = None,
) -> ClientUser:
    """Turn off portal access and revoke live sessions.

    Magic-link and session checks read ``disabled_at``. Revoking sessions
    records the existing logout event. ``ClientActivityEvent`` has no
    portal-access type, so this does not add one.
    """
    client_user.disabled_at = timezone.now()
    client_user.save(update_fields=["disabled_at", "modified"])
    revoke_all_client_sessions(client_user, request=request)
    expire_unused(MagicLoginToken.objects.filter(client_user=client_user))
    return client_user


def reenable_client_user(client_user: ClientUser) -> ClientUser:
    """Restore portal access. ``disabled_at`` is the only flag those checks use."""
    client_user.disabled_at = None
    client_user.save(update_fields=["disabled_at", "modified"])
    return client_user
