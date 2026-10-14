from __future__ import annotations

import json
from http import HTTPStatus

import pytest
from django.core.exceptions import ValidationError
from django.test import Client as HttpClient
from django.urls import reverse
from django_tenants.utils import schema_context

from break_instantiation_backend.children.models import Child
from break_instantiation_backend.clients.models import Client
from break_instantiation_backend.users.models import User
from break_instantiation_backend.users.roles import StaffRole

pytestmark = pytest.mark.django_db

PASSWORD = "test"  # noqa: S105


def _post(client: HttpClient, url_name: str, data: dict):
    return client.post(
        reverse(url_name),
        data=json.dumps(data),
        content_type="application/json",
    )


def test_localhost_admin_shows_every_company():
    with schema_context("public"):
        User.objects.create_superuser("test@test.com", PASSWORD)
    with schema_context("ej"):
        Client.objects.create(full_name="EJ Person", email="person@ej.test")
    with schema_context("break"):
        Client.objects.create(full_name="Break Person", email="person@break.test")

    http = HttpClient(HTTP_HOST="localhost")
    assert http.get("/admin/login/").status_code == HTTPStatus.OK
    logged_in = http.post(
        "/admin/login/",
        {"username": "test@test.com", "password": PASSWORD, "next": "/admin/"},
    )
    assert logged_in.status_code == HTTPStatus.FOUND

    index = http.get("/admin/")
    assert index.status_code == HTTPStatus.OK
    assert http.get("/admin/clients/client/").status_code == HTTPStatus.FORBIDDEN
    companies = http.get("/admin/children/child/")
    assert companies.status_code == HTTPStatus.OK
    page = companies.content.decode()
    assert "EJ" in page
    assert "Break" in page

    with schema_context("public"):
        ej = Child.objects.get(schema_name="ej")
    detail = http.get(f"/admin/children/child/{ej.pk}/change/")
    assert detail.status_code == HTTPStatus.OK
    roster = detail.content.decode()
    assert "person@ej.test" in roster
    assert "person@break.test" not in roster


def test_public_backend_admin_opens_one_company():
    with schema_context("public"):
        User.objects.create_superuser("test@test.com", PASSWORD)
    with schema_context("ej"):
        User.objects.create_user(
            "admin@ej.test",
            PASSWORD,
            role=StaffRole.ADMIN,
        )
        Client.objects.create(full_name="EJ Person", email="person@ej.test")
    with schema_context("break"):
        Client.objects.create(full_name="Break Person", email="person@break.test")

    http = HttpClient(HTTP_HOST="ej.test")
    company_admin = http.post(
        "/admin/login/",
        {"username": "admin@ej.test", "password": PASSWORD, "next": "/admin/"},
    )
    assert company_admin.status_code == HTTPStatus.OK
    assert http.get("/admin/clients/client/").status_code == HTTPStatus.FOUND

    logged_in = http.post(
        "/admin/login/",
        {"username": "test@test.com", "password": PASSWORD, "next": "/admin/"},
    )
    assert logged_in.status_code == HTTPStatus.FOUND
    clients = http.get("/admin/clients/client/")
    assert clients.status_code == HTTPStatus.OK
    page = clients.content.decode()
    assert "person@ej.test" in page
    assert "person@break.test" not in page
    assert http.get("/admin/children/child/").status_code == HTTPStatus.FORBIDDEN


def test_unknown_host_sees_nothing(client):
    response = client.get("/api/staff/me/", HTTP_HOST="missing.test")
    assert response.status_code == HTTPStatus.NOT_FOUND


def test_roles_stay_in_their_own_schema():
    with schema_context("public"), pytest.raises(ValidationError):
        User.objects.create_user(
            "admin@public.test",
            PASSWORD,
            role=StaffRole.ADMIN,
        )
    with schema_context("ej"), pytest.raises(ValidationError):
        User.objects.create_user(
            "overseer@ej.test",
            PASSWORD,
            role=StaffRole.BACKEND_ADMIN,
        )


def test_admins_cannot_see_the_other_childs_client():
    with schema_context("ej"):
        ej_admin = User.objects.create_user(
            "admin@ej.test",
            PASSWORD,
            role=StaffRole.ADMIN,
        )
        Client.objects.create(full_name="EJ Person", email="person@ej.test")
    with schema_context("break"):
        break_admin = User.objects.create_user(
            "admin@break.test",
            PASSWORD,
            role=StaffRole.ADMIN,
        )
        Client.objects.create(full_name="Break Person", email="person@break.test")

    ej_http = HttpClient(HTTP_HOST="ej.test")
    with schema_context("ej"):
        ej_http.force_login(ej_admin)
    ej_listing = ej_http.get(reverse("api:client-list"))
    assert ej_listing.status_code == HTTPStatus.OK
    assert {row["email"] for row in ej_listing.json()} == {"person@ej.test"}

    break_http = HttpClient(HTTP_HOST="break.test")
    with schema_context("break"):
        break_http.force_login(break_admin)
    break_listing = break_http.get(reverse("api:client-list"))
    assert break_listing.status_code == HTTPStatus.OK
    assert {row["email"] for row in break_listing.json()} == {"person@break.test"}


def test_public_backend_admin_oversees_both_children_and_lives_only_on_public():
    with schema_context("public"):
        User.objects.create_superuser("test@test.com", PASSWORD)
    with schema_context("ej"):
        Client.objects.create(full_name="EJ Person", email="person@ej.test")
        assert not User.objects.filter(email="test@test.com").exists()
    with schema_context("break"):
        Client.objects.create(full_name="Break Person", email="person@break.test")
        assert not User.objects.filter(email="test@test.com").exists()

    ej_http = HttpClient(HTTP_HOST="ej.test")
    logged_in = _post(
        ej_http,
        "api:staff:login",
        {"email": "test@test.com", "password": PASSWORD},
    )
    assert logged_in.status_code == HTTPStatus.OK
    assert logged_in.json()["role"] == StaffRole.BACKEND_ADMIN
    ej_listing = ej_http.get(reverse("api:client-list"))
    assert {row["email"] for row in ej_listing.json()} == {"person@ej.test"}
    ej_id = ej_listing.json()[0]["id"]
    renamed = ej_http.patch(
        reverse("api:client-detail", kwargs={"pk": ej_id}),
        data=json.dumps({"full_name": "EJ Person Updated"}),
        content_type="application/json",
    )
    assert renamed.status_code == HTTPStatus.OK

    break_http = HttpClient(HTTP_HOST="break.test")
    break_login = _post(
        break_http,
        "api:staff:login",
        {"email": "test@test.com", "password": PASSWORD},
    )
    assert break_login.status_code == HTTPStatus.OK
    break_listing = break_http.get(reverse("api:client-list"))
    assert break_listing.status_code == HTTPStatus.OK
    assert {row["email"] for row in break_listing.json()} == {"person@break.test"}
    assert break_listing.json()[0]["full_name"] == "Break Person"


def test_draft_host_hides_the_portal_and_answers_its_admin():
    with schema_context("draft"):
        User.objects.create_user(
            "admin@draft.test",
            PASSWORD,
            role=StaffRole.ADMIN,
        )
    anonymous = HttpClient(HTTP_HOST="draft.test")
    portal = _post(
        anonymous,
        "api:client_auth:magic-login-request",
        {"email": "nobody@example.com"},
    )
    assert portal.status_code == HTTPStatus.NOT_FOUND

    staff = HttpClient(HTTP_HOST="draft.test")
    logged_in = _post(
        staff,
        "api:staff:login",
        {"email": "admin@draft.test", "password": PASSWORD},
    )
    assert logged_in.status_code == HTTPStatus.OK
    assert staff.get(reverse("api:staff:me")).status_code == HTTPStatus.OK
    assert staff.get(reverse("api:client-list")).status_code == HTTPStatus.OK
