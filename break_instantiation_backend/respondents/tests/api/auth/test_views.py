from __future__ import annotations

import json
from http import HTTPStatus
from urllib.parse import parse_qs
from urllib.parse import urlparse

import pytest
from django.core.cache import cache
from django.urls import reverse
from django.utils import timezone

from break_instantiation_backend.respondents.api.auth.views import (
    MagicLoginRequestIPThrottle,
)
from break_instantiation_backend.respondents.api.auth.views import (
    MagicLoginRequestThrottle,
)
from break_instantiation_backend.respondents.models import RespondentSession
from break_instantiation_backend.respondents.tests.factories import RespondentFactory
from break_instantiation_backend.respondents.tests.factories import (
    RespondentSessionFactory,
)
from break_instantiation_backend.tokens import generate_token
from break_instantiation_backend.tokens import hash_token

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
        respondent = RespondentFactory.create()

        known = _post(
            client,
            "api:respondent_auth:magic-login-request",
            {"email": respondent.email},
        )
        unknown = _post(
            client,
            "api:respondent_auth:magic-login-request",
            {"email": "nobody@example.com"},
        )

        assert known.status_code == HTTPStatus.OK
        assert unknown.status_code == HTTPStatus.OK
        assert known.json() == unknown.json()

    def test_sends_link_that_redeems(
        self,
        client,
        settings,
        mailoutbox,
    ):
        settings.CELERY_TASK_ALWAYS_EAGER = True
        respondent = RespondentFactory.create()

        _post(
            client,
            "api:respondent_auth:magic-login-request",
            {"email": respondent.email},
            HTTP_ORIGIN="https://child.example.com",
        )

        assert len(mailoutbox) == 1
        assert mailoutbox[0].to == [respondent.email]
        link = next(
            line
            for line in mailoutbox[0].body.splitlines()
            if line.startswith("https://child.example.com/magic-login?")
        )
        raw_token = parse_qs(urlparse(link).query)["token"][0]
        redeem = _post(
            client,
            "api:respondent_auth:magic-login-redeem",
            {"token": raw_token},
        )

        assert redeem.status_code == HTTPStatus.OK
        assert redeem.json() == {"email": respondent.email}
        assert "respondent_session" in redeem.cookies
        assert redeem.cookies["respondent_session"]["max-age"] == ""
        stored = RespondentSession.objects.get(respondent=respondent)
        cookie = redeem.cookies["respondent_session"].value
        assert stored.token_hash == hash_token(cookie)

    def test_no_email_for_disabled_respondent(self, client, settings, mailoutbox):
        settings.CELERY_TASK_ALWAYS_EAGER = True
        respondent = RespondentFactory.create(disabled_at=timezone.now())

        response = _post(
            client,
            "api:respondent_auth:magic-login-request",
            {"email": respondent.email},
        )

        assert response.status_code == HTTPStatus.OK
        assert len(mailoutbox) == 0

    def test_throttled_per_email(self, client, monkeypatch):
        monkeypatch.setattr(
            MagicLoginRequestThrottle,
            "THROTTLE_RATES",
            {"magic_login": "1/hour"},
        )
        respondent = RespondentFactory.create()

        first = _post(
            client,
            "api:respondent_auth:magic-login-request",
            {"email": respondent.email},
        )
        second = _post(
            client,
            "api:respondent_auth:magic-login-request",
            {"email": respondent.email},
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
            "api:respondent_auth:magic-login-request",
            {"email": "nobody-1@example.com"},
        )
        second = _post(
            client,
            "api:respondent_auth:magic-login-request",
            {"email": "nobody-2@example.com"},
        )

        assert first.status_code == HTTPStatus.OK
        assert second.status_code == HTTPStatus.TOO_MANY_REQUESTS


class TestMagicLoginRedeemView:
    def test_invalid_token(self, client):
        response = _post(
            client,
            "api:respondent_auth:magic-login-redeem",
            {"token": "garbage"},
        )

        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_second_redeem_rejected(self, client, settings, mailoutbox):
        settings.CELERY_TASK_ALWAYS_EAGER = True
        respondent = RespondentFactory.create()
        _post(
            client,
            "api:respondent_auth:magic-login-request",
            {"email": respondent.email},
            HTTP_ORIGIN="http://localhost:5173",
        )
        link = next(
            line for line in mailoutbox[0].body.splitlines() if "magic-login?" in line
        )
        raw_token = parse_qs(urlparse(link).query)["token"][0]

        first = _post(
            client,
            "api:respondent_auth:magic-login-redeem",
            {"token": raw_token},
        )
        second = _post(
            client,
            "api:respondent_auth:magic-login-redeem",
            {"token": raw_token},
        )

        assert first.status_code == HTTPStatus.OK
        assert second.status_code == HTTPStatus.BAD_REQUEST


class TestRespondentLogoutView:
    def test_logout_revokes_session_and_clears_cookie(self, client):
        session = RespondentSessionFactory.create()
        raw_token = _with_raw_session(session)
        client.cookies["respondent_session"] = raw_token

        response = client.post(reverse("api:respondent_auth:logout"))

        assert response.status_code == HTTPStatus.NO_CONTENT
        session.refresh_from_db()
        assert session.revoked_at is not None
        assert response.cookies["respondent_session"].value == ""

    def test_logout_without_cookie_is_forbidden(self, client):
        response = client.post(reverse("api:respondent_auth:logout"))

        assert response.status_code == HTTPStatus.FORBIDDEN


class TestRespondentLogoutAllView:
    def test_logout_all_revokes_every_session(self, client):
        respondent = RespondentFactory.create()
        session = RespondentSessionFactory.create(respondent=respondent)
        other = RespondentSessionFactory.create(respondent=respondent)
        raw_token = _with_raw_session(session)
        client.cookies["respondent_session"] = raw_token

        response = client.post(reverse("api:respondent_auth:logout-all"))

        assert response.status_code == HTTPStatus.NO_CONTENT
        session.refresh_from_db()
        other.refresh_from_db()
        assert session.revoked_at is not None
        assert other.revoked_at is not None
