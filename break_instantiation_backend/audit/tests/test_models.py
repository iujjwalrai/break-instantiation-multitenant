from __future__ import annotations

import pytest
from django.db import IntegrityError
from django.db import transaction

from break_instantiation_backend.audit.models import AdminActivityEvent
from break_instantiation_backend.audit.models import AdminActivityEventType
from break_instantiation_backend.audit.models import AssessmentActivityEvent
from break_instantiation_backend.audit.models import AssessmentActivityEventType
from break_instantiation_backend.audit.models import AuthEvent
from break_instantiation_backend.audit.models import AuthEventType
from break_instantiation_backend.audit.models import ClientActivityEvent
from break_instantiation_backend.audit.models import ClientActivityEventType
from break_instantiation_backend.clients.tests.factories import ClientFactory
from break_instantiation_backend.clients.tests.factories import ClientUserFactory
from break_instantiation_backend.users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db


def test_auth_event_requires_exactly_one_identity():
    user = UserFactory.create()
    client_user = ClientUserFactory.create()

    with pytest.raises(IntegrityError), transaction.atomic():
        AuthEvent.objects.create(
            user=user,
            client_user=client_user,
            event_type=AuthEventType.LOGIN_SUCCESS,
        )

    with pytest.raises(IntegrityError), transaction.atomic():
        AuthEvent.objects.create(event_type=AuthEventType.LOGIN_SUCCESS)


def test_auth_event_cannot_be_updated_or_deleted():
    event = AuthEvent.objects.create(
        user=UserFactory.create(),
        event_type=AuthEventType.LOGIN_SUCCESS,
    )

    with pytest.raises(ValueError, match="append-only"):
        event.save()
    with pytest.raises(ValueError, match="append-only"):
        event.delete()


def test_admin_activity_event_cannot_be_updated_or_deleted():
    event = AdminActivityEvent.objects.create(
        actor_user=UserFactory.create(),
        event_type=AdminActivityEventType.USER_CREATED,
    )

    with pytest.raises(ValueError, match="append-only"):
        event.save()
    with pytest.raises(ValueError, match="append-only"):
        event.delete()


def test_client_activity_event_cannot_be_updated_or_deleted():
    event = ClientActivityEvent.objects.create(
        actor_user=UserFactory.create(),
        client=ClientFactory.create(),
        event_type=ClientActivityEventType.CLIENT_CREATED,
    )

    with pytest.raises(ValueError, match="append-only"):
        event.save()
    with pytest.raises(ValueError, match="append-only"):
        event.delete()


def test_assessment_activity_event_cannot_be_updated_or_deleted():
    event = AssessmentActivityEvent.objects.create(
        client=ClientFactory.create(),
        event_type=AssessmentActivityEventType.CONSENT_GRANTED,
    )

    with pytest.raises(ValueError, match="append-only"):
        event.save()
    with pytest.raises(ValueError, match="append-only"):
        event.delete()
