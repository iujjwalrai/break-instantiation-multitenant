import tempfile
from pathlib import Path
from typing import Any

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.core.management.base import CommandError
from django_tenants.utils import schema_context

from break_instantiation_backend.children.models import Child
from break_instantiation_backend.children.models import ChildDomain
from break_instantiation_backend.children.models import ChildStatus
from break_instantiation_backend.clients.models import Client
from break_instantiation_backend.users.models import User
from break_instantiation_backend.users.roles import StaffRole

# Local dev fixture, the same password as the public god account. Not a
# production secret.
DEV_PASSWORD = "test"  # noqa: S105

# Same five paragraphs as the BVI consent screen. `{company}` is the child
# name, so each company stores the wording its own clients are shown.
CONSENT_TEXT = (
    Path(__file__).resolve().parents[3] / "questionnaires" / "seed" / "consent_v1.txt"
)
CONSENT_VERSION = "v1"

CHILDREN = (
    {
        "schema_name": "ej",
        "name": "EJ",
        "domain": "ej.localhost",
        "client_site_url": "http://ej.localhost:3001",
        "look": {
            "name": "EJ",
            "logo": "",
            "colors": {
                "primary": "#1B4D3E",
                "primaryForeground": "#ffffff",
                "primaryHover": "#14382D",
            },
        },
        "admin_email": "admin@ej.test",
        "client_name": "EJ Client",
        "client_email": "client@ej.test",
    },
    {
        "schema_name": "break",
        "name": "Break",
        "domain": "break.localhost",
        "client_site_url": "http://break.localhost:3001",
        "look": {
            "name": "Break",
            "logo": "",
            "colors": {
                "primary": "#1A2744",
                "primaryForeground": "#ffffff",
                "primaryHover": "#121B30",
            },
        },
        "admin_email": "admin@break.test",
        "client_name": "Break Client",
        "client_email": "client@break.test",
    },
)


class Command(BaseCommand):
    help = (
        "Create the local EJ and Break children, one admin and one client "
        "in each, and the public god account. Dev fixture only."
    )

    def handle(self, *args: Any, **options: Any) -> None:
        if not settings.DEBUG:
            msg = "seed_local_children is a local dev fixture."
            raise CommandError(msg)
        _ensure_god_account()
        for spec in CHILDREN:
            _ensure_child(spec)
        self.stdout.write(self.style.SUCCESS("Local children are ready."))
        self.stdout.write(
            "Public admin: http://localhost:8000/admin/  test@test.com / test",
        )
        self.stdout.write(
            "Same login opens one company: "
            "http://ej.localhost:8000/admin/ and http://break.localhost:8000/admin/",
        )
        self.stdout.write(
            "Client sites: http://ej.localhost:3001 and http://break.localhost:3001",
        )


def _ensure_god_account() -> None:
    with schema_context("public"):
        user = User.objects.filter(email="test@test.com").first()
        if user is None:
            user = User.objects.create_superuser("test@test.com", DEV_PASSWORD)
        else:
            user.set_password(DEV_PASSWORD)
        user.is_staff = True
        user.is_superuser = True
        user.role = StaffRole.BACKEND_ADMIN
        user.save()


def _ensure_child(spec: dict) -> None:
    with schema_context("public"):
        child = Child.objects.filter(schema_name=spec["schema_name"]).first()
        if child is None:
            child = Child(
                schema_name=spec["schema_name"],
                name=spec["name"],
                status=ChildStatus.LIVE,
                client_site_url=spec["client_site_url"],
                look=spec["look"],
            )
            child.save()
        else:
            child.name = spec["name"]
            child.status = ChildStatus.LIVE
            child.client_site_url = spec["client_site_url"]
            child.look = spec["look"]
            child.save()
        ChildDomain.objects.get_or_create(
            domain=spec["domain"],
            defaults={"tenant": child, "is_primary": True},
        )
    with schema_context(spec["schema_name"]):
        admin = User.objects.filter(email=spec["admin_email"]).first()
        if admin is None:
            User.objects.create_user(
                spec["admin_email"],
                DEV_PASSWORD,
                role=StaffRole.ADMIN,
            )
        else:
            admin.role = StaffRole.ADMIN
            admin.set_password(DEV_PASSWORD)
            admin.save()
        Client.objects.get_or_create(
            email=spec["client_email"],
            defaults={"full_name": spec["client_name"]},
        )
        _ensure_consent(spec["look"]["name"])


def _ensure_consent(company: str) -> None:
    text = CONSENT_TEXT.read_text(encoding="utf-8").replace("{company}", company)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        suffix=".txt",
        delete=False,
    ) as handle:
        handle.write(text)
        path = handle.name
    try:
        call_command("seed_consent_template", CONSENT_VERSION, path, "--activate")
    finally:
        Path(path).unlink(missing_ok=True)
