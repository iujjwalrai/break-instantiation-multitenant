from __future__ import annotations

import json
from http import HTTPStatus

import pytest
from django.urls import reverse

from break_instantiation_backend.users.models import User
from break_instantiation_backend.users.roles import StaffRole
from break_instantiation_backend.users.tests.factories import UserFactory

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


def test_super_admin_creates_an_admin(client):
    super_admin = UserFactory.create(
        role=StaffRole.SUPER_ADMIN,
        is_superuser=True,
        password=PASSWORD,
    )
    client.force_login(super_admin)

    response = _post(
        client,
        "api:staff:admins",
        {
            "email": "owner@example.com",
            "name": "Owner",
            "password": PASSWORD,
        },
    )

    assert response.status_code == HTTPStatus.CREATED
    created = User.objects.get(email="owner@example.com")
    assert created.role == StaffRole.ADMIN
    assert created.check_password(PASSWORD)


def test_admin_cannot_create_an_admin(client):
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

    assert response.status_code == HTTPStatus.FORBIDDEN
    assert not User.objects.filter(email="other@example.com").exists()
