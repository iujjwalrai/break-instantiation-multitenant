from __future__ import annotations

import json
from http import HTTPStatus
from urllib.parse import parse_qs
from urllib.parse import urlparse

import pytest
from django.core.cache import cache
from django.urls import reverse
from django.utils import timezone

from break_instantiation_backend.audit.models import ClientActivityEvent
from break_instantiation_backend.audit.models import ClientActivityEventType
from break_instantiation_backend.clients.api.auth.views import (
    MagicLoginRequestIPThrottle,
)
from break_instantiation_backend.clients.api.auth.views import MagicLoginRequestThrottle
from break_instantiation_backend.clients.models import ClientSession
from break_instantiation_backend.clients.models import ClientUser
from break_instantiation_backend.clients.tests.factories import ClientFactory
from break_instantiation_backend.clients.tests.factories import ClientSessionFactory
from break_instantiation_backend.clients.tests.factories import ClientUserFactory
from break_instantiation_backend.tokens import generate_token
from break_instantiation_backend.tokens import hash_token
from break_instantiation_backend.users.roles import StaffRole
from break_instantiation_backend.users.tests.factories import UserFactory
from break_instantiation_backend.users.tests.tenancy import create_public_backend_admin

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _clear_throttle_cache():
    cache.clear()
    yield
    cache.clear()


def _post(client, url_name, data, **extra):
    return client.post(
        reverse(url_name),
        data=json.dumps(data),
        content_type="application/json",
        **extra,
    )


def _with_raw_session(session):
    raw_token = generate_token()
    session.token_hash = hash_token(raw_token)
    session.save(update_fields=["token_hash"])
    return raw_token


class TestMagicLoginRequestView:
    def test_response_identical_whether_or_not_email_exists(self, client):
        client_user = ClientUserFactory.create()

        known = _post(
            client,
            "api:client_auth:magic-login-request",
            {"email": client_user.email},
        )
        unknown = _post(
            client,
            "api:client_auth:magic-login-request",
            {"email": "nobody@example.com"},
        )

        assert known.status_code == HTTPStatus.OK
        assert unknown.status_code == HTTPStatus.OK
        assert known.json() == unknown.json()

    def test_profile_without_login_gets_no_mail(self, client, settings, mailoutbox):
        settings.CELERY_TASK_ALWAYS_EAGER = True
        profile = ClientFactory.create()

        response = _post(
            client,
            "api:client_auth:magic-login-request",
            {"email": profile.email},
            HTTP_ORIGIN="https://child.example.com",
        )

        assert response.status_code == HTTPStatus.OK
        assert len(mailoutbox) == 0

    def test_sends_link_that_redeems(self, client, settings, mailoutbox):
        settings.CELERY_TASK_ALWAYS_EAGER = True
        client_user = ClientUserFactory.create()

        _post(
            client,
            "api:client_auth:magic-login-request",
            {"email": client_user.email},
            HTTP_ORIGIN="https://child.example.com",
        )

        assert len(mailoutbox) == 1
        assert mailoutbox[0].to == [client_user.email]
        link = next(
            line
            for line in mailoutbox[0].body.splitlines()
            if line.startswith("http://localhost:3001/magic-login?")
        )
        raw_token = parse_qs(urlparse(link).query)["token"][0]
        redeem = _post(
            client,
            "api:client_auth:magic-login-redeem",
            {"token": raw_token},
        )

        assert redeem.status_code == HTTPStatus.OK
        assert redeem.json() == {"email": client_user.email}
        assert "client_session" in redeem.cookies
        assert redeem.cookies["client_session"]["max-age"] == ""
        stored = ClientSession.objects.get(client_user=client_user)
        cookie = redeem.cookies["client_session"].value
        assert stored.token_hash == hash_token(cookie)

    def test_no_email_for_disabled_client_user(self, client, settings, mailoutbox):
        settings.CELERY_TASK_ALWAYS_EAGER = True
        client_user = ClientUserFactory.create(disabled_at=timezone.now())

        response = _post(
            client,
            "api:client_auth:magic-login-request",
            {"email": client_user.email},
        )

        assert response.status_code == HTTPStatus.OK
        assert len(mailoutbox) == 0

    def test_throttled_per_email(self, client, monkeypatch):
        monkeypatch.setattr(
            MagicLoginRequestThrottle,
            "THROTTLE_RATES",
            {"magic_login": "1/hour"},
        )
        client_user = ClientUserFactory.create()

        first = _post(
            client,
            "api:client_auth:magic-login-request",
            {"email": client_user.email},
        )
        second = _post(
            client,
            "api:client_auth:magic-login-request",
            {"email": client_user.email},
        )

        assert first.status_code == HTTPStatus.OK
        assert second.status_code == HTTPStatus.TOO_MANY_REQUESTS

    def test_throttled_by_ip_across_emails(self, client, monkeypatch):
        monkeypatch.setattr(
            MagicLoginRequestIPThrottle,
            "THROTTLE_RATES",
            {"magic_login_ip": "1/hour"},
        )

        first = _post(
            client,
            "api:client_auth:magic-login-request",
            {"email": "nobody-1@example.com"},
        )
        second = _post(
            client,
            "api:client_auth:magic-login-request",
            {"email": "nobody-2@example.com"},
        )

        assert first.status_code == HTTPStatus.OK
        assert second.status_code == HTTPStatus.TOO_MANY_REQUESTS


class TestMagicLoginRedeemView:
    def test_invalid_token(self, client):
        response = _post(
            client,
            "api:client_auth:magic-login-redeem",
            {"token": "garbage"},
        )

        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_second_redeem_rejected(self, client, settings, mailoutbox):
        settings.CELERY_TASK_ALWAYS_EAGER = True
        client_user = ClientUserFactory.create()
        _post(
            client,
            "api:client_auth:magic-login-request",
            {"email": client_user.email},
            HTTP_ORIGIN="http://localhost:5173",
        )
        link = next(
            line for line in mailoutbox[0].body.splitlines() if "magic-login?" in line
        )
        raw_token = parse_qs(urlparse(link).query)["token"][0]

        first = _post(
            client,
            "api:client_auth:magic-login-redeem",
            {"token": raw_token},
        )
        second = _post(
            client,
            "api:client_auth:magic-login-redeem",
            {"token": raw_token},
        )

        assert first.status_code == HTTPStatus.OK
        assert second.status_code == HTTPStatus.BAD_REQUEST


class TestPortalLogoutView:
    def test_logout_revokes_session_and_clears_cookie(self, client):
        session = ClientSessionFactory.create()
        raw_token = _with_raw_session(session)
        client.cookies["client_session"] = raw_token

        response = client.post(reverse("api:client_auth:logout"))

        assert response.status_code == HTTPStatus.NO_CONTENT
        session.refresh_from_db()
        assert session.revoked_at is not None
        assert response.cookies["client_session"].value == ""

    def test_logout_without_cookie_is_forbidden(self, client):
        response = client.post(reverse("api:client_auth:logout"))

        assert response.status_code == HTTPStatus.FORBIDDEN


class TestPortalLogoutAllView:
    def test_logout_all_revokes_every_session(self, client):
        client_user = ClientUserFactory.create()
        session = ClientSessionFactory.create(client_user=client_user)
        other = ClientSessionFactory.create(client_user=client_user)
        raw_token = _with_raw_session(session)
        client.cookies["client_session"] = raw_token

        response = client.post(reverse("api:client_auth:logout-all"))

        assert response.status_code == HTTPStatus.NO_CONTENT
        session.refresh_from_db()
        other.refresh_from_db()
        assert session.revoked_at is not None
        assert other.revoked_at is not None


class TestPortalInvite:
    def test_invite_email_creates_client_user_on_redeem(
        self,
        client,
        settings,
        mailoutbox,
    ):
        settings.CELERY_TASK_ALWAYS_EAGER = True
        admin = UserFactory.create(role=StaffRole.ADMIN)
        client.force_login(admin)
        created = _post(
            client,
            "api:client-list",
            {"full_name": "Ada Lovelace", "email": "ada@example.com"},
            HTTP_ORIGIN="http://localhost:5173",
        )
        assert created.status_code == HTTPStatus.CREATED
        assert ClientActivityEvent.objects.filter(
            client__email="ada@example.com",
            actor_user=admin,
            event_type=ClientActivityEventType.CLIENT_CREATED,
        ).exists()
        assert created.json()["has_login"] is False
        assert "admin" not in created.json()

        invited = client.post(
            reverse("api:client-invite", kwargs={"pk": created.json()["id"]}),
            HTTP_ORIGIN="http://localhost:5173",
        )
        assert invited.status_code == HTTPStatus.ACCEPTED
        assert len(mailoutbox) == 1
        link = next(
            line
            for line in mailoutbox[0].body.splitlines()
            if line.startswith("http://localhost:3001/invite?")
        )
        raw_token = parse_qs(urlparse(link).query)["token"][0]

        client.logout()
        redeem = _post(
            client,
            "api:client_auth:invite-redeem",
            {"token": raw_token},
        )

        assert redeem.status_code == HTTPStatus.OK
        assert redeem.json() == {"email": "ada@example.com"}
        assert "client_session" in redeem.cookies
        assert ClientUser.objects.filter(email="ada@example.com").exists()

    def test_admin_sees_every_client(self, client):
        other = UserFactory.create(role=StaffRole.ADMIN)
        profile = ClientFactory.create(email="hidden@example.com")
        client.force_login(other)

        listing = client.get(reverse("api:client-list"))
        detail = client.get(reverse("api:client-detail", kwargs={"pk": profile.id}))

        assert listing.status_code == HTTPStatus.OK
        assert {row["email"] for row in listing.json()} == {"hidden@example.com"}
        assert detail.status_code == HTTPStatus.OK

    def test_backend_admin_sees_every_client(self, client):
        backend_admin = create_public_backend_admin(
            "backend@example.com",
            "something-r@nd0m!",
        )
        ClientFactory.create(email="owned@example.com")
        logged_in = _post(
            client,
            "api:staff:login",
            {
                "email": backend_admin.email,
                "password": "something-r@nd0m!",
            },
        )
        assert logged_in.status_code == HTTPStatus.OK

        listing = client.get(reverse("api:client-list"))

        assert listing.status_code == HTTPStatus.OK
        assert {row["email"] for row in listing.json()} == {"owned@example.com"}


def _patch(client, pk, data):
    return client.patch(
        reverse("api:client-detail", kwargs={"pk": pk}),
        data=json.dumps(data),
        content_type="application/json",
    )


class TestClientUpdate:
    def test_admin_updates_name_and_email(self, client):
        admin = UserFactory.create(role=StaffRole.ADMIN)
        profile = ClientFactory.create(email="ada@example.com", full_name="Ada")
        client.force_login(admin)

        response = _patch(
            client,
            profile.id,
            {"full_name": "Ada Lovelace", "email": "ada.lovelace@example.com"},
        )

        assert response.status_code == HTTPStatus.OK
        assert response.json()["full_name"] == "Ada Lovelace"
        assert response.json()["email"] == "ada.lovelace@example.com"
        assert "admin" not in response.json()
        profile.refresh_from_db()
        assert profile.full_name == "Ada Lovelace"
        assert profile.email == "ada.lovelace@example.com"
        event = ClientActivityEvent.objects.get(client=profile)
        assert event.event_type == ClientActivityEventType.CLIENT_UPDATED
        assert event.actor_user == admin
        assert event.changes == {
            "full_name": {"old": "Ada", "new": "Ada Lovelace"},
            "email": {"old": "ada@example.com", "new": "ada.lovelace@example.com"},
        }

    def test_assignment_payload_is_ignored(self, client):
        admin = UserFactory.create(role=StaffRole.ADMIN)
        profile = ClientFactory.create(full_name="Ada", email="ada@example.com")
        client.force_login(admin)

        response = _patch(client, profile.id, {"admin": admin.id})

        assert response.status_code == HTTPStatus.OK
        assert response.json()["full_name"] == "Ada"
        assert "admin" not in response.json()
        assert not ClientActivityEvent.objects.filter(client=profile).exists()

    def test_backend_admin_updates_a_client(self, client):
        backend_admin = create_public_backend_admin(
            "backend@example.com",
            "something-r@nd0m!",
        )
        profile = ClientFactory.create(full_name="Ada")
        logged_in = _post(
            client,
            "api:staff:login",
            {
                "email": backend_admin.email,
                "password": "something-r@nd0m!",
            },
        )
        assert logged_in.status_code == HTTPStatus.OK

        response = _patch(client, profile.id, {"full_name": "Ada Lovelace"})

        assert response.status_code == HTTPStatus.OK
        assert response.json()["full_name"] == "Ada Lovelace"
        profile.refresh_from_db()
        assert profile.full_name == "Ada Lovelace"
        event = ClientActivityEvent.objects.get(client=profile)
        assert event.actor_user_id is None
        assert event.external_actor_email == "backend@example.com"
