from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from break_instantiation_backend.respondents.models import MagicLoginToken
from break_instantiation_backend.respondents.services import issue_magic_login
from break_instantiation_backend.respondents.services import redeem_magic_login
from break_instantiation_backend.respondents.services import resolve_respondent_session
from break_instantiation_backend.respondents.tests.factories import RespondentFactory
from break_instantiation_backend.sessions import SessionExpiredError
from break_instantiation_backend.tokens import TokenExpiredError
from break_instantiation_backend.tokens import TokenInvalidError
from break_instantiation_backend.tokens import hash_token

from .factories import RespondentSessionFactory

pytestmark = pytest.mark.django_db


def test_new_link_expires_older_unused_links():
    respondent = RespondentFactory.create()
    first, first_raw = issue_magic_login(respondent=respondent)
    _second, second_raw = issue_magic_login(respondent=respondent)

    first.refresh_from_db()
    assert first.expires_at <= timezone.now()
    assert first.token_hash == hash_token(first_raw)
    assert MagicLoginToken.objects.get(token_hash=hash_token(second_raw)).used is False


def test_redeem_marks_token_used_and_opens_session():
    respondent = RespondentFactory.create()
    _token, raw = issue_magic_login(respondent=respondent)

    signed_in, session, raw_session = redeem_magic_login(raw)

    assert signed_in == respondent
    assert session.token_hash == hash_token(raw_session)
    assert session.token_hash != raw_session
    with pytest.raises(TokenInvalidError):
        redeem_magic_login(raw)


def test_redeem_expired_token():
    respondent = RespondentFactory.create()
    _token, raw = issue_magic_login(
        respondent=respondent,
        ttl=timedelta(minutes=-1),
    )

    with pytest.raises(TokenExpiredError):
        redeem_magic_login(raw)


def test_idle_session_expires():
    session = RespondentSessionFactory.create(
        expires_at=timezone.now() - timedelta(seconds=1),
    )
    raw = "not-the-stored-value"
    session.token_hash = hash_token(raw)
    session.save(update_fields=["token_hash"])

    with pytest.raises(SessionExpiredError):
        resolve_respondent_session(raw)
