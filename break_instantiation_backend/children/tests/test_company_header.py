import json
from http import HTTPStatus

import pytest
from django.test import Client as HttpClient
from django_tenants.utils import schema_context

from break_instantiation_backend.users.models import User
from break_instantiation_backend.users.roles import StaffRole

pytestmark = pytest.mark.django_db

SECRET = "frontend-shared-secret"  # noqa: S105
PASSWORD = "Adm1n-r@nd0m-pass"  # noqa: S105


@pytest.fixture
def secret(settings):
    settings.COMPANY_HOST_SECRET = SECRET


def _look(http: HttpClient, **headers) -> tuple[int, str]:
    response = http.get("/api/look/", headers=headers)
    if response.status_code != HTTPStatus.OK:
        return response.status_code, ""
    return response.status_code, response.json()["name"]


def test_header_picks_the_company_on_a_shared_api_host(secret):
    # testserver is the "test" company. The header overrides it.
    http = HttpClient()

    assert _look(http) == (HTTPStatus.OK, "Test")
    assert _look(http, x_company_host="ej.test", x_company_key=SECRET) == (
        HTTPStatus.OK,
        "EJ",
    )
    assert _look(http, x_company_host="BREAK.test:3002", x_company_key=SECRET) == (
        HTTPStatus.OK,
        "Break",
    )


def test_header_is_ignored_when_no_secret_is_configured(settings):
    settings.COMPANY_HOST_SECRET = ""

    status, name = _look(HttpClient(), x_company_host="ej.test", x_company_key="x")

    assert (status, name) == (HTTPStatus.OK, "Test")


@pytest.mark.parametrize("key", ["", "wrong-secret"])
def test_header_without_the_shared_key_is_refused(secret, key):
    status, _name = _look(HttpClient(), x_company_host="ej.test", x_company_key=key)

    assert status == HTTPStatus.FORBIDDEN


@pytest.mark.parametrize("named", ["localhost", "127.0.0.1", "nobody.test"])
def test_header_never_reaches_public_or_an_unknown_company(secret, named):
    status, _name = _look(HttpClient(), x_company_host=named, x_company_key=SECRET)

    assert status == HTTPStatus.NOT_FOUND


def test_a_session_from_one_company_is_not_valid_in_another(secret):
    with schema_context("break"):
        User.objects.create_user("admin@break.test", PASSWORD, role=StaffRole.ADMIN)
    http = HttpClient()
    as_break = {"x_company_host": "break.test", "x_company_key": SECRET}
    as_ej = {"x_company_host": "ej.test", "x_company_key": SECRET}

    login = http.post(
        "/api/staff/login/",
        data=json.dumps({"email": "admin@break.test", "password": PASSWORD}),
        content_type="application/json",
        headers=as_break,
    )

    assert login.status_code == HTTPStatus.OK
    assert http.get("/api/staff/me/", headers=as_break).status_code == HTTPStatus.OK
    assert http.get("/api/staff/me/", headers=as_ej).status_code == HTTPStatus.FORBIDDEN
