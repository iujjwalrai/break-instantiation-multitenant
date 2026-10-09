from __future__ import annotations

import typing

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from break_instantiation_backend.sessions import SessionExpiredError
from break_instantiation_backend.sessions import SessionInvalidError
from break_instantiation_backend.tokens import TokenInvalidError
from break_instantiation_backend.tokens import expire_unused
from break_instantiation_backend.tokens import generate_token
from break_instantiation_backend.tokens import hash_token
from break_instantiation_backend.tokens import redeem
from break_instantiation_backend.tokens import verify

from .models import Client
from .models import ClientPortalInvite
from .models import ClientSession
from .models import ClientUser
from .models import MagicLoginToken

if typing.TYPE_CHECKING:
    from datetime import timedelta

    from break_instantiation_backend.users.models import User


def issue_portal_invite(
    *,
    target_client: Client,
    invited_by: User,
    ttl: timedelta | None = None,
) -> tuple[ClientPortalInvite, str]:
    """Create an invite and hard-expire older unused ones for this client."""
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
) -> tuple[ClientUser, ClientSession, str]:
    """Consume an invite, create the `ClientUser`, and start a session."""
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
                )
        session, raw_session_token = issue_client_session(client_user=client_user)
    return client_user, session, raw_session_token


def issue_magic_login(
    *,
    client_user: ClientUser,
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
    return token, raw_token


def redeem_magic_login(
    raw_token: str,
) -> tuple[ClientUser, ClientSession, str]:
    """Consume a magic-login token and start a session."""
    with transaction.atomic():
        token = redeem(MagicLoginToken, raw_token)
        if token.client_user.disabled_at is not None:
            msg = "This account has been disabled."
            raise TokenInvalidError(msg)
        session, raw_session_token = issue_client_session(client_user=token.client_user)
    return token.client_user, session, raw_session_token


def issue_client_session(*, client_user: ClientUser) -> tuple[ClientSession, str]:
    """Open a session. Does not revoke sessions this client already holds."""
    raw_token = generate_token()
    now = timezone.now()
    session = ClientSession.objects.create(
        client_user=client_user,
        token_hash=hash_token(raw_token),
        expires_at=now + settings.CLIENT_SESSION_IDLE_TTL,
        last_used_at=now,
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


def revoke_client_session(raw_token: str) -> None:
    """Revoke the session for this device. A second logout is a no-op."""
    try:
        session = ClientSession.objects.get(token_hash=hash_token(raw_token))
    except ClientSession.DoesNotExist as exc:
        msg = "Session not found."
        raise SessionInvalidError(msg) from exc
    if session.revoked_at is not None:
        return
    session.revoked_at = timezone.now()
    session.save(update_fields=["revoked_at", "modified"])


def revoke_all_client_sessions(client_user: ClientUser) -> int:
    """Revoke every live session for `client_user`. Returns how many closed."""
    return ClientSession.objects.filter(
        client_user=client_user,
        revoked_at__isnull=True,
    ).update(revoked_at=timezone.now())
