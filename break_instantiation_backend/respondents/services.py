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

from .models import MagicLoginToken
from .models import Respondent
from .models import RespondentSession

if typing.TYPE_CHECKING:
    from datetime import timedelta


def issue_magic_login(
    *,
    respondent: Respondent,
    ttl: timedelta | None = None,
) -> tuple[MagicLoginToken, str]:
    """Create a magic-login token and hard-expire older unused ones.

    Returns `(token, raw_token)`. The raw token is for the email only.
    """
    raw_token = generate_token()
    with transaction.atomic():
        expire_unused(MagicLoginToken.objects.filter(respondent=respondent))
        token = MagicLoginToken.objects.create(
            respondent=respondent,
            token_hash=hash_token(raw_token),
            expires_at=timezone.now() + (ttl or settings.MAGIC_LOGIN_TOKEN_TTL),
        )
    return token, raw_token


def redeem_magic_login(
    raw_token: str,
) -> tuple[Respondent, RespondentSession, str]:
    """Consume a magic-login token and start a session.

    Returns `(respondent, session, raw_session_token)`.
    """
    with transaction.atomic():
        token = redeem(MagicLoginToken, raw_token)
        if token.respondent.disabled_at is not None:
            msg = "This account has been disabled."
            raise TokenInvalidError(msg)
        session, raw_session_token = issue_respondent_session(
            respondent=token.respondent,
        )
    return token.respondent, session, raw_session_token


def issue_respondent_session(
    *,
    respondent: Respondent,
) -> tuple[RespondentSession, str]:
    """Open a session. Does not revoke sessions the respondent already holds."""
    raw_token = generate_token()
    now = timezone.now()
    session = RespondentSession.objects.create(
        respondent=respondent,
        token_hash=hash_token(raw_token),
        expires_at=now + settings.RESPONDENT_SESSION_IDLE_TTL,
        last_used_at=now,
    )
    return session, raw_token


def resolve_respondent_session(raw_token: str) -> RespondentSession:
    """Look up an active session and slide its idle window when due."""
    try:
        session = RespondentSession.objects.select_related("respondent").get(
            token_hash=hash_token(raw_token),
        )
    except RespondentSession.DoesNotExist as exc:
        msg = "Session not found."
        raise SessionInvalidError(msg) from exc
    if session.revoked_at is not None:
        msg = "Session has been revoked."
        raise SessionInvalidError(msg)
    if session.respondent.disabled_at is not None:
        msg = "Respondent is disabled."
        raise SessionInvalidError(msg)
    now = timezone.now()
    if session.expires_at <= now:
        msg = "Session has expired."
        raise SessionExpiredError(msg)
    if now - session.last_used_at > settings.SESSION_SLIDE_THRESHOLD:
        session.last_used_at = now
        session.expires_at = now + settings.RESPONDENT_SESSION_IDLE_TTL
        session.save(update_fields=["last_used_at", "expires_at", "modified"])
    return session


def revoke_respondent_session(raw_token: str) -> None:
    """Revoke the session for this device. A second logout is a no-op."""
    try:
        session = RespondentSession.objects.get(token_hash=hash_token(raw_token))
    except RespondentSession.DoesNotExist as exc:
        msg = "Session not found."
        raise SessionInvalidError(msg) from exc
    if session.revoked_at is not None:
        return
    session.revoked_at = timezone.now()
    session.save(update_fields=["revoked_at", "modified"])


def revoke_all_respondent_sessions(respondent: Respondent) -> int:
    """Revoke every live session for `respondent`. Returns how many closed."""
    return RespondentSession.objects.filter(
        respondent=respondent,
        revoked_at__isnull=True,
    ).update(revoked_at=timezone.now())
