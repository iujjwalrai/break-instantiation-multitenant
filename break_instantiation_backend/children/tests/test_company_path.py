import json
from http import HTTPStatus

import pytest
from asgiref.sync import async_to_sync
from django.test import AsyncClient
from django.test import Client as HttpClient
from django_tenants.utils import schema_context

from break_instantiation_backend.users.models import User
from break_instantiation_backend.users.roles import StaffRole

pytestmark = pytest.mark.django_db

PASSWORD = "Adm1n-r@nd0m-pass"  # noqa: S105


def _look(http: HttpClient, path: str) -> tuple[int, str]:
    response = http.get(path)
    if response.status_code != HTTPStatus.OK:
        return response.status_code, ""
    return response.status_code, response.json()["name"]


def test_path_picks_the_company_on_one_api_host():
    # localhost is a public host: its root is the control store.
    http = HttpClient(headers={"host": "localhost"})

    assert _look(http, "/t/ej/api/look/") == (HTTPStatus.OK, "EJ")
    assert _look(http, "/t/break/api/look/") == (HTTPStatus.OK, "Break")
    assert _look(http, "/api/look/") == (HTTPStatus.NOT_FOUND, "")


def test_company_host_still_works_at_the_root():
    assert _look(HttpClient(), "/api/look/") == (HTTPStatus.OK, "Test")
    assert _look(HttpClient(headers={"host": "ej.test"}), "/api/look/") == (
        HTTPStatus.OK,
        "EJ",
    )


@pytest.mark.parametrize(
    "path",
    ["/t/nobody/api/look/", "/t/EJ/api/look/", "/t/ej.test/api/look/", "/t/public/"],
)
def test_unknown_or_malformed_slugs_are_not_found(path):
    status, _name = _look(HttpClient(headers={"host": "localhost"}), path)

    assert status == HTTPStatus.NOT_FOUND


def test_unknown_host_is_not_found():
    status, _name = _look(HttpClient(headers={"host": "nobody.test"}), "/api/look/")

    assert status == HTTPStatus.NOT_FOUND


def test_reverse_keeps_the_company_prefix():
    response = HttpClient(headers={"host": "localhost"}).get("/t/ej/admin/login/")

    assert response.status_code == HTTPStatus.OK
    assert 'action="/t/ej/admin/login/' in response.content.decode()


def test_session_is_scoped_to_its_company_path_and_schema():
    with schema_context("break"):
        User.objects.create_user("admin@break.test", PASSWORD, role=StaffRole.ADMIN)
    http = HttpClient(headers={"host": "localhost"})

    login = http.post(
        "/t/break/api/staff/login/",
        data=json.dumps({"email": "admin@break.test", "password": PASSWORD}),
        content_type="application/json",
    )

    assert login.status_code == HTTPStatus.OK
    assert login.cookies["sessionid"]["path"] == "/t/break/"
    assert login.cookies["csrftoken"]["path"] == "/t/break/"
    assert http.get("/t/break/api/staff/me/").status_code == HTTPStatus.OK
    # The test client sends every cookie, so this proves the schema check.
    assert http.get("/t/ej/api/staff/me/").status_code == HTTPStatus.FORBIDDEN


def test_draft_company_by_path_answers_only_open_paths():
    http = HttpClient(headers={"host": "localhost"})

    assert _look(http, "/t/draft/api/look/") == (HTTPStatus.OK, "Draft")
    assert http.get("/t/draft/api/clients/").status_code == HTTPStatus.NOT_FOUND


def test_company_path_works_through_the_asgi_handler():
    # Render and local dev serve ASGI. The URL is resolved on the event loop
    # thread there, not the thread where the middleware picked the company.
    response = async_to_sync(AsyncClient(headers={"host": "localhost"}).get)(
        "/t/ej/api/look/",
    )

    assert response.status_code == HTTPStatus.OK
    assert response.json()["name"] == "EJ"


def test_company_list_on_the_public_host_shows_live_companies():
    response = HttpClient(headers={"host": "localhost"}).get("/api/companies/")

    assert response.status_code == HTTPStatus.OK
    rows = {row["slug"]: row["name"] for row in response.json()}
    assert rows["ej"] == "EJ"
    assert rows["break"] == "Break"
    assert "draft" not in rows
    assert "public" not in rows


def test_company_list_is_not_served_inside_a_company():
    response = HttpClient(headers={"host": "localhost"}).get("/t/ej/api/companies/")

    assert response.status_code == HTTPStatus.NOT_FOUND


def test_company_cookie_wins_over_a_public_cookie_of_the_same_name():
    # A browser signed in to /admin/ and /t/break/ sends both sessionids to
    # /t/break/, the longer path first. Django keeps the last by default.
    with schema_context("break"):
        User.objects.create_user("admin@break.test", PASSWORD, role=StaffRole.ADMIN)
    login = HttpClient(headers={"host": "localhost"}).post(
        "/t/break/api/staff/login/",
        data=json.dumps({"email": "admin@break.test", "password": PASSWORD}),
        content_type="application/json",
    )
    company_session = login.cookies["sessionid"].value
    both = f"sessionid={company_session}; sessionid=public-session-value"

    response = HttpClient(headers={"host": "localhost", "cookie": both}).get(
        "/t/break/api/staff/me/",
    )

    assert response.status_code == HTTPStatus.OK
