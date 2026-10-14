from __future__ import annotations

import json
from http import HTTPStatus

import pytest
from django.urls import reverse
from django.utils import timezone

from break_instantiation_backend.audit.models import ClientActivityEvent
from break_instantiation_backend.audit.models import ClientActivityEventType
from break_instantiation_backend.clients.tests.factories import ClientFactory
from break_instantiation_backend.questionnaires.tests.factories import (
    ConsentRecordFactory,
)
from break_instantiation_backend.users.roles import StaffRole
from break_instantiation_backend.users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db


def _post(client, url_name, pk):
    return client.post(
        reverse(url_name, kwargs={"pk": pk}),
        data=json.dumps({}),
        content_type="application/json",
    )


class TestStaffConsent:
    def test_withdraw_and_reinstate(self, client):
        admin = UserFactory.create(role=StaffRole.ADMIN)
        target = ClientFactory.create()
        record = ConsentRecordFactory.create(client=target)
        client.force_login(admin)

        withdrawn = _post(client, "api:client-withdraw-consent", target.pk)

        assert withdrawn.status_code == HTTPStatus.OK
        assert withdrawn.json()["consent_granted_at"] is None
        record.refresh_from_db()
        assert record.withdrawn_at is not None
        assert ClientActivityEvent.objects.filter(
            client=target,
            event_type=ClientActivityEventType.CONSENT_WITHDRAWN,
            actor_user=admin,
        ).exists()

        restored = _post(client, "api:client-reinstate-consent", target.pk)

        assert restored.status_code == HTTPStatus.OK
        record.refresh_from_db()
        assert record.withdrawn_at is None
        granted_at = restored.json()["consent_granted_at"]
        assert granted_at is not None
        assert ClientActivityEvent.objects.filter(
            client=target,
            event_type=ClientActivityEventType.CONSENT_REINSTATED,
            actor_user=admin,
        ).exists()

    def test_withdraw_without_a_grant_is_rejected(self, client):
        admin = UserFactory.create(role=StaffRole.ADMIN)
        target = ClientFactory.create()
        client.force_login(admin)

        response = _post(client, "api:client-withdraw-consent", target.pk)

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert not ClientActivityEvent.objects.filter(
            event_type=ClientActivityEventType.CONSENT_WITHDRAWN,
        ).exists()

    def test_anonymous_cannot_withdraw(self, client):
        target = ClientFactory.create()
        ConsentRecordFactory.create(client=target, withdrawn_at=timezone.now())

        response = _post(client, "api:client-withdraw-consent", target.pk)

        assert response.status_code == HTTPStatus.FORBIDDEN
