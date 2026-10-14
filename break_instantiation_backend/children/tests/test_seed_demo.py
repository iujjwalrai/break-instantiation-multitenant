import json

import pytest
from django.contrib.auth import authenticate
from django.core.management import CommandError
from django.core.management import call_command
from django_tenants.utils import schema_context

from break_instantiation_backend.children.management.commands.seed_demo import CLIENTS
from break_instantiation_backend.children.management.commands.seed_demo import (
    parse_children,
)
from break_instantiation_backend.children.models import Child
from break_instantiation_backend.children.models import ChildDomain
from break_instantiation_backend.clients.models import Client
from break_instantiation_backend.questionnaires.models import ConsentTemplate
from break_instantiation_backend.users.models import User
from break_instantiation_backend.users.roles import StaffRole
from break_instantiation_backend.users.roles import is_backend_admin

pytestmark = pytest.mark.django_db

PASSWORD = "demo-r@nd0m-pass"  # noqa: S105
EJ = {
    "schema_name": "ej",
    "name": "EJ",
    "client_site_url": "https://portal.example.com/ej",
}


def _seed(*children: dict, password: str = PASSWORD) -> None:
    call_command("seed_demo", password=password, children=json.dumps(children))


def test_seeds_backend_admin_company_admin_clients_and_consent():
    _seed(EJ)

    with schema_context("public"):
        backend = authenticate(email="backend-admin@example.com", password=PASSWORD)
        assert backend is not None
        assert backend.role == StaffRole.BACKEND_ADMIN
        assert is_backend_admin(backend)
        ej = Child.objects.get(schema_name="ej")
        assert ej.client_site_url == "https://portal.example.com/ej"
        # The slug defaults to the schema name: /t/ej/.
        assert ChildDomain.objects.get(domain="ej").tenant == ej

    with schema_context("ej"):
        admin = authenticate(email="admin@ej.example.com", password=PASSWORD)
        assert admin is not None
        assert admin.role == StaffRole.ADMIN
        assert Client.objects.count() == len(CLIENTS)
        assert Client.objects.get(email="acme@example.com").client_user is not None
        assert Client.objects.get(email="initech@example.com").client_user is None
        assert "EJ" in ConsentTemplate.objects.get(is_active=True).text


def test_rerun_resets_passwords_and_keeps_demo_changes():
    _seed(EJ)
    with schema_context("ej"):
        initech = Client.objects.get(email="initech@example.com")
        initech.full_name = "Initech Renamed"
        initech.save()

    _seed(EJ, password="another-r@nd0m-pass")  # noqa: S106

    with schema_context("ej"):
        initech.refresh_from_db()
        assert initech.full_name == "Initech Renamed"
        assert Client.objects.count() == len(CLIENTS)
        assert ConsentTemplate.objects.count() == 1
        assert authenticate(email="admin@ej.example.com", password=PASSWORD) is None
        assert (
            authenticate(email="admin@ej.example.com", password="another-r@nd0m-pass")  # noqa: S106
            is not None
        )
    with schema_context("public"):
        assert ChildDomain.objects.filter(domain="ej").count() == 1


def test_creates_a_new_company_schema():
    _seed(
        {
            "schema_name": "acmedemo",
            "name": "Acme Demo",
            "client_site_url": "https://acme-portal.example.com",
            "admin_email": "owner@acme.example.com",
        },
    )

    with schema_context("public"):
        child = Child.objects.get(schema_name="acmedemo")
        assert child.domains.get().is_primary
    with schema_context("acmedemo"):
        assert User.objects.get(email="owner@acme.example.com").role == StaffRole.ADMIN
        assert Client.objects.count() == len(CLIENTS)


def test_refuses_a_domain_owned_by_another_company():
    with pytest.raises(CommandError, match="another company"):
        _seed({**EJ, "domains": ["break"]})


def test_requires_password():
    with pytest.raises(CommandError, match="DJANGO_DEMO_PASSWORD"):
        _seed(EJ, password="")


def test_default_is_one_company_called_demo():
    children = parse_children("", default_site="https://portal.example.com/demo")
    assert children == [
        {
            "schema_name": "demo",
            "name": "Demo",
            "client_site_url": "https://portal.example.com/demo",
            "domains": ["demo"],
            "look": {"name": "Demo"},
        },
    ]


def test_company_can_have_several_paths_and_hosts():
    _seed(
        {
            **EJ,
            "domains": ["ej", "EJ-Wealth", "ej.example.com"],
        },
    )

    with schema_context("public"):
        hosts = set(
            ChildDomain.objects.filter(tenant__schema_name="ej").values_list(
                "domain",
                flat=True,
            ),
        )
    assert {"ej", "ej-wealth", "ej.example.com"} <= hosts


def test_name_and_look_follow_the_env_on_every_run():
    _seed({**EJ, "look": {"colors": {"primary": "#1B4D3E"}}})
    _seed(
        {
            **EJ,
            "name": "EJ Wealth",
            "look": {"logo": "https://cdn.example.com/ej.svg"},
        },
    )

    with schema_context("public"):
        ej = Child.objects.get(schema_name="ej")
    assert ej.name == "EJ Wealth"
    assert ej.look == {"name": "EJ Wealth", "logo": "https://cdn.example.com/ej.svg"}


def test_rejects_a_bad_look():
    bad = json.dumps([{**EJ, "look": {"colors": {"primary": "red"}}}])
    with pytest.raises(CommandError, match="bad look"):
        parse_children(bad, "")


def test_rejects_incomplete_or_public_companies():
    no_site = {**EJ, "client_site_url": ""}
    with pytest.raises(CommandError, match="missing client_site_url"):
        parse_children(json.dumps([no_site]), "")
    public = {**EJ, "schema_name": "public"}
    with pytest.raises(CommandError, match="public schema"):
        parse_children(json.dumps([public]), "")
    bad_slug = {**EJ, "domains": ["ej/admin"]}
    with pytest.raises(CommandError, match="bad path slugs"):
        parse_children(json.dumps([bad_slug]), "")
