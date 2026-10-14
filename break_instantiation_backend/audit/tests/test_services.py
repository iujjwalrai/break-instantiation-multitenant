from __future__ import annotations

import pytest
from django.test import RequestFactory

from break_instantiation_backend.audit.models import AuthEventType
from break_instantiation_backend.audit.services import USER_AGENT_MAX_LENGTH
from break_instantiation_backend.audit.services import record_event
from break_instantiation_backend.clients.tests.factories import ClientUserFactory
from break_instantiation_backend.users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db


def test_record_event_requires_exactly_one_identity():
    user = UserFactory.create()
    client_user = ClientUserFactory.create()

    with pytest.raises(ValueError, match="exactly one"):
        record_event(AuthEventType.LOGIN_SUCCESS)
    with pytest.raises(ValueError, match="exactly one"):
        record_event(
            AuthEventType.LOGIN_SUCCESS,
            user=user,
            client_user=client_user,
        )


def test_record_event_derives_ip_and_user_agent_from_request():
    user = UserFactory.create()
    request = RequestFactory().get(
        "/",
        REMOTE_ADDR="203.0.113.5",
        HTTP_USER_AGENT="pytest-agent",
    )

    event = record_event(AuthEventType.LOGIN_SUCCESS, user=user, request=request)

    assert event.ip_address == "203.0.113.5"
    assert event.user_agent == "pytest-agent"


def test_record_event_truncates_long_user_agent():
    user = UserFactory.create()
    long_agent = "a" * (USER_AGENT_MAX_LENGTH + 50)
    request = RequestFactory().get("/", HTTP_USER_AGENT=long_agent)

    event = record_event(AuthEventType.LOGIN_SUCCESS, user=user, request=request)

    assert event.user_agent == long_agent[:USER_AGENT_MAX_LENGTH]


def test_explicit_ip_wins_over_request():
    user = UserFactory.create()
    request = RequestFactory().get("/", REMOTE_ADDR="203.0.113.5")

    event = record_event(
        AuthEventType.LOGIN_SUCCESS,
        user=user,
        request=request,
        ip_address="198.51.100.9",
    )

    assert event.ip_address == "198.51.100.9"


def test_record_event_ignores_forwarded_for_unless_trusted(settings):
    settings.TRUST_X_FORWARDED_FOR_IP = False
    user = UserFactory.create()
    request = RequestFactory().get(
        "/",
        REMOTE_ADDR="203.0.113.5",
        HTTP_X_FORWARDED_FOR="1.2.3.4, 198.51.100.9",
    )

    event = record_event(AuthEventType.LOGIN_SUCCESS, user=user, request=request)

    assert event.ip_address == "203.0.113.5"

    settings.TRUST_X_FORWARDED_FOR_IP = True
    trusted = record_event(AuthEventType.LOGOUT, user=user, request=request)

    assert trusted.ip_address == "198.51.100.9"
