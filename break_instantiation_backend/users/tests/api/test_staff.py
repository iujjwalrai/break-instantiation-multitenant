from __future__ import annotations

import json
from http import HTTPStatus

import pytest
from django.urls import reverse

from break_instantiation_backend.audit.models import AdminActivityEvent
from break_instantiation_backend.audit.models import AdminActivityEventType
from break_instantiation_backend.audit.models import AuthEvent
from break_instantiation_backend.audit.models import AuthEventType
from break_instantiation_backend.users.models import User
from break_instantiation_backend.users.roles import StaffRole
from break_instantiation_backend.users.tests.factories import UserFactory
from break_instantiation_backend.users.tests.tenancy import create_public_backend_admin

pytestmark = pytest.mark.django_db

PASSWORD = "something-r@nd0m!"  # noqa: S105


def _post(client, url_name, data):
    return client.post(
        reverse(url_name),
        data=json.dumps(data),
        content_type="application/json",
    )


def test_admin_can_log_in(client):
    admin = UserFactory.create(role=StaffRole.ADMIN, password=PASSWORD)

    response = _post(
        client,
        "api:staff:login",
        {"email": admin.email, "password": PASSWORD},
    )

    assert response.status_code == HTTPStatus.OK
    assert response.json()["role"] == StaffRole.ADMIN
    assert AuthEvent.objects.filter(
        user=admin,
        event_type=AuthEventType.LOGIN_SUCCESS,
    ).exists()
    me = client.get(reverse("api:staff:me"))
    assert me.json()["email"] == admin.email


def test_clientless_user_cannot_log_in(client):
    user = UserFactory.create(password=PASSWORD)

    response = _post(
        client,
        "api:staff:login",
        {"email": user.email, "password": PASSWORD},
    )

    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert client.get(reverse("api:staff:me")).status_code == HTTPStatus.FORBIDDEN
    assert AuthEvent.objects.filter(
        user=user,
        event_type=AuthEventType.LOGIN_FAILURE,
    ).exists()


def test_admin_with_superuser_flag_stays_an_admin(client):
    admin = UserFactory.create(
        role=StaffRole.ADMIN,
        is_superuser=True,
        password=PASSWORD,
    )

    response = _post(
        client,
        "api:staff:login",
        {"email": admin.email, "password": PASSWORD},
    )

    assert response.status_code == HTTPStatus.OK
    assert response.json()["role"] == StaffRole.ADMIN


def test_superuser_flag_signs_in_as_backend_admin(client):
    backend_admin = create_public_backend_admin(
        "flagged@example.com",
        PASSWORD,
        role="",
    )

    response = _post(
        client,
        "api:staff:login",
        {"email": backend_admin.email, "password": PASSWORD},
    )

    assert response.status_code == HTTPStatus.OK
    assert response.json()["role"] == StaffRole.BACKEND_ADMIN
    clients = client.get(reverse("api:client-list"))
    assert clients.status_code == HTTPStatus.OK


def test_backend_admin_creates_an_admin(client):
    backend_admin = create_public_backend_admin("backend@example.com", PASSWORD)
    logged_in = _post(
        client,
        "api:staff:login",
        {"email": backend_admin.email, "password": PASSWORD},
    )
    assert logged_in.status_code == HTTPStatus.OK

    response = _post(
        client,
        "api:staff:admins",
        {
            "email": "other@example.com",
            "name": "Other",
            "password": PASSWORD,
        },
    )

    assert response.status_code == HTTPStatus.CREATED
    created = User.objects.get(email="other@example.com")
    assert created.role == StaffRole.ADMIN


def test_admin_lists_other_admins(client):
    admin = UserFactory.create(role=StaffRole.ADMIN, email="admin@example.com")
    UserFactory.create(role=StaffRole.ADMIN, email="other@example.com")
    create_public_backend_admin("backend@example.com", PASSWORD)
    client.force_login(admin)

    response = client.get(reverse("api:staff:admins"))

    assert response.status_code == HTTPStatus.OK
    assert {row["email"] for row in response.json()} == {
        "admin@example.com",
        "other@example.com",
    }


def test_admin_creates_an_admin(client):
    admin = UserFactory.create(role=StaffRole.ADMIN, password=PASSWORD)
    client.force_login(admin)

    response = _post(
        client,
        "api:staff:admins",
        {
            "email": "other@example.com",
            "password": PASSWORD,
        },
    )

    assert response.status_code == HTTPStatus.CREATED
    created = User.objects.get(email="other@example.com")
    assert created.role == StaffRole.ADMIN
    assert AdminActivityEvent.objects.filter(
        actor_user=admin,
        target_user=created,
        event_type=AdminActivityEventType.USER_CREATED,
        new_role_name=StaffRole.ADMIN,
    ).exists()
