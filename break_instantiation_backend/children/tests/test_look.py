from http import HTTPStatus

import pytest
from django.core.exceptions import ValidationError
from django.test import Client as HttpClient
from django_tenants.utils import schema_context

from break_instantiation_backend.children.models import Child

pytestmark = pytest.mark.django_db

EJ_LOOK = {
    "name": "EJ",
    "logo": "",
    "colors": {
        "primary": "#1B4D3E",
        "primaryForeground": "#ffffff",
        "primaryHover": "#14382D",
    },
}
BREAK_LOOK = {
    "name": "Break",
    "logo": "https://cdn.example.com/break.svg",
    "colors": {
        "primary": "#1A2744",
        "primaryForeground": "#ffffff",
        "primaryHover": "#121B30",
    },
}


def test_each_host_returns_that_company_look():
    with schema_context("public"):
        Child.objects.filter(schema_name="ej").update(look=EJ_LOOK)
        Child.objects.filter(schema_name="break").update(look=BREAK_LOOK)

    ej = HttpClient(HTTP_HOST="ej.test").get("/api/look/")
    assert ej.status_code == HTTPStatus.OK
    assert ej.json()["name"] == "EJ"
    assert ej.json()["colors"]["primary"] == "#1B4D3E"
    assert ej.json()["logo"] == ""

    other = HttpClient(HTTP_HOST="break.test").get("/api/look/")
    assert other.status_code == HTTPStatus.OK
    assert other.json()["name"] == "Break"
    assert other.json()["colors"]["primary"] == "#1A2744"
    assert other.json()["logo"] == "https://cdn.example.com/break.svg"


def test_public_host_has_no_company_look():
    response = HttpClient(HTTP_HOST="localhost").get("/api/look/")
    assert response.status_code == HTTPStatus.NOT_FOUND


def test_empty_look_uses_the_company_name_and_default_colors():
    with schema_context("public"):
        Child.objects.filter(schema_name="draft").update(look={})

    response = HttpClient(HTTP_HOST="draft.test").get("/api/look/")
    assert response.status_code == HTTPStatus.OK
    body = response.json()
    assert body["name"] == "Draft"
    assert body["colors"] == {
        "primary": "#000000",
        "primaryForeground": "#ffffff",
        "primaryHover": "#808080",
    }


def test_look_rejects_a_color_that_is_not_hex():
    with schema_context("public"):
        child = Child.objects.get(schema_name="ej")
    child.look = {"colors": {"primary": "green"}}
    with pytest.raises(ValidationError):
        child.full_clean()
