from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from break_instantiation_backend.clients.models import ClientUser
from break_instantiation_backend.clients.models import MagicLoginToken
from break_instantiation_backend.clients.services import issue_magic_login
from break_instantiation_backend.clients.services import issue_portal_invite
from break_instantiation_backend.clients.services import redeem_magic_login
from break_instantiation_backend.clients.services import redeem_portal_invite
from break_instantiation_backend.clients.services import resolve_client_session
from break_instantiation_backend.clients.tests.factories import ClientFactory
from break_instantiation_backend.clients.tests.factories import ClientSessionFactory
from break_instantiation_backend.clients.tests.factories import ClientUserFactory
from break_instantiation_backend.sessions import SessionExpiredError
from break_instantiation_backend.tokens import TokenExpiredError
from break_instantiation_backend.tokens import TokenInvalidError
from break_instantiation_backend.tokens import hash_token
from break_instantiation_backend.users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db


def test_new_link_expires_older_unused_links():
    client_user = ClientUserFactory.create()
    first, first_raw = issue_magic_login(client_user=client_user)
    _second, second_raw = issue_magic_login(client_user=client_user)

    first.refresh_from_db()
    assert first.expires_at <= timezone.now()
    assert first.token_hash == hash_token(first_raw)
    stored = MagicLoginToken.objects.get(token_hash=hash_token(second_raw))
    assert stored.used is False


def test_redeem_marks_token_used_and_opens_session():
    client_user = ClientUserFactory.create()
    _token, raw = issue_magic_login(client_user=client_user)

    signed_in, session, raw_session = redeem_magic_login(raw)

    assert signed_in == client_user
    assert session.token_hash == hash_token(raw_session)
    assert session.token_hash != raw_session
    with pytest.raises(TokenInvalidError):
        redeem_magic_login(raw)


def test_redeem_expired_token():
    client_user = ClientUserFactory.create()
    _token, raw = issue_magic_login(
        client_user=client_user,
        ttl=timedelta(minutes=-1),
    )

    with pytest.raises(TokenExpiredError):
        redeem_magic_login(raw)


def test_idle_session_expires():
    session = ClientSessionFactory.create(
        expires_at=timezone.now() - timedelta(seconds=1),
    )
    raw = "not-the-stored-value"
    session.token_hash = hash_token(raw)
    session.save(update_fields=["token_hash"])

    with pytest.raises(SessionExpiredError):
        resolve_client_session(raw)


def test_redeem_invite_creates_client_user_and_links_profile():
    profile = ClientFactory.create(email="ada@example.com")
    inviter = UserFactory.create()
    _invite, raw = issue_portal_invite(target_client=profile, invited_by=inviter)

    client_user, session, raw_session = redeem_portal_invite(raw)

    profile.refresh_from_db()
    assert client_user.email == "ada@example.com"
    assert profile.client_user == client_user
    assert ClientUser.objects.filter(email="ada@example.com").count() == 1
    assert session.token_hash == hash_token(raw_session)
    with pytest.raises(TokenInvalidError):
        redeem_portal_invite(raw)


def test_new_invite_expires_older_unused_invites():
    profile = ClientFactory.create()
    inviter = UserFactory.create()
    first, _first_raw = issue_portal_invite(target_client=profile, invited_by=inviter)
    issue_portal_invite(target_client=profile, invited_by=inviter)

    first.refresh_from_db()
    assert first.expires_at <= timezone.now()


def test_redeem_invite_rejects_email_linked_to_another_client():
    taken = ClientUserFactory.create(email="ada@example.com")
    ClientFactory.create(email="other@example.com", client_user=taken)
    profile = ClientFactory.create(email="ada@example.com")
    inviter = UserFactory.create()
    _invite, raw = issue_portal_invite(target_client=profile, invited_by=inviter)

    with pytest.raises(TokenInvalidError, match="different client"):
        redeem_portal_invite(raw)

    profile.refresh_from_db()
    assert profile.client_user_id is None
