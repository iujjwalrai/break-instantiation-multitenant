"""Demo companies and logins for the Render deploy. Safe to re-run.

The free instance reboots on every wake, so this runs on every boot.
Passwords and each company's client site follow the env vars every run.
Companies, clients, and consent wording are only created when missing, so
whatever the demo changed survives a restart.
"""

import json
import os
from typing import Any

from django.core.management.base import BaseCommand
from django.core.management.base import CommandError
from django_tenants.utils import get_public_schema_name
from django_tenants.utils import schema_context

from break_instantiation_backend.children.management.commands.seed_local_children import (  # noqa: E501
    _ensure_consent,
)
from break_instantiation_backend.children.models import Child
from break_instantiation_backend.children.models import ChildDomain
from break_instantiation_backend.children.models import ChildStatus
from break_instantiation_backend.clients.models import Client
from break_instantiation_backend.clients.models import ClientUser
from break_instantiation_backend.questionnaires.models import ConsentTemplate
from break_instantiation_backend.users.models import User
from break_instantiation_backend.users.roles import StaffRole

# full name, email, has a portal login. Invite the one without a login.
CLIENTS = (
    ("Acme Holdings", "acme@example.com", True),
    ("Globex Partners", "globex@example.com", True),
    ("Initech Ltd", "initech@example.com", False),
)


def parse_children(raw: str, default_domain: str, default_site: str) -> list[dict]:
    """`DJANGO_DEMO_CHILDREN` JSON, or one company on the Render host.

    Each entry: schema_name, name, domain (the API host the frontends call),
    client_site_url (the customer portal), and optional admin_email.
    """
    if raw.strip():
        try:
            children = json.loads(raw)
        except json.JSONDecodeError as exc:
            msg = f"DJANGO_DEMO_CHILDREN is not valid JSON: {exc}"
            raise CommandError(msg) from exc
    elif default_domain:
        children = [
            {
                "schema_name": "demo",
                "name": "Demo",
                "domain": default_domain,
                "client_site_url": default_site,
            },
        ]
    else:
        msg = "Set DJANGO_DEMO_CHILDREN, or RENDER_EXTERNAL_HOSTNAME for one company."
        raise CommandError(msg)

    required = ("schema_name", "name", "domain", "client_site_url")
    for child in children:
        missing = [key for key in required if not child.get(key)]
        if missing:
            msg = f"Demo company {child} is missing {', '.join(missing)}."
            raise CommandError(msg)
        if child["schema_name"] == get_public_schema_name():
            msg = "A demo company cannot use the public schema."
            raise CommandError(msg)
    return children


class Command(BaseCommand):
    help = "Create demo companies, a backend admin, admins, and clients."

    def add_arguments(self, parser):
        parser.add_argument(
            "--password",
            default=os.environ.get("DJANGO_DEMO_PASSWORD", ""),
            help="Password for every staff login. Defaults to $DJANGO_DEMO_PASSWORD.",
        )
        parser.add_argument(
            "--children",
            default=os.environ.get("DJANGO_DEMO_CHILDREN", ""),
            help="JSON list of companies. Defaults to $DJANGO_DEMO_CHILDREN.",
        )
        parser.add_argument(
            "--backend-admin-email",
            default=os.environ.get(
                "DJANGO_DEMO_BACKEND_ADMIN_EMAIL",
                "backend-admin@example.com",
            ),
        )

    def handle(self, *args: Any, **options: Any) -> None:
        password = options["password"]
        if not password:
            msg = "Pass --password or set DJANGO_DEMO_PASSWORD."
            raise CommandError(msg)
        children = parse_children(
            options["children"],
            default_domain=os.environ.get("RENDER_EXTERNAL_HOSTNAME", ""),
            default_site=os.environ.get("DJANGO_DEMO_CLIENT_SITE_URL", ""),
        )

        _ensure_backend_admin(options["backend_admin_email"], password)
        for spec in children:
            _ensure_child(spec, password)
            self.stdout.write(
                f"{spec['name']}: API host {spec['domain']}, "
                f"admin {_admin_email(spec)}",
            )
        self.stdout.write(
            self.style.SUCCESS(f"Seeded {len(children)} demo companies."),
        )


def _admin_email(spec: dict) -> str:
    return spec.get("admin_email") or f"admin@{spec['schema_name']}.example.com"


def _ensure_backend_admin(email: str, password: str) -> None:
    with schema_context(get_public_schema_name()):
        user = User.objects.filter(email__iexact=email).first()
        if user is None:
            user = User.objects.create_superuser(email, password)
        else:
            user.set_password(password)
        user.is_staff = True
        user.is_superuser = True
        user.role = StaffRole.BACKEND_ADMIN
        user.save()


def _ensure_child(spec: dict, password: str) -> None:
    with schema_context(get_public_schema_name()):
        child = Child.objects.filter(schema_name=spec["schema_name"]).first()
        if child is None:
            # Saving creates and migrates the schema.
            child = Child(
                schema_name=spec["schema_name"],
                name=spec["name"],
                status=ChildStatus.LIVE,
                client_site_url=spec["client_site_url"],
                look={"name": spec["name"]},
            )
            child.save()
        elif child.client_site_url != spec["client_site_url"]:
            child.client_site_url = spec["client_site_url"]
            child.save(update_fields=["client_site_url"])

        domain = ChildDomain.objects.filter(domain=spec["domain"]).first()
        if domain is None:
            ChildDomain.objects.create(
                domain=spec["domain"],
                tenant=child,
                is_primary=not child.domains.exists(),
            )
        elif domain.tenant_id != child.pk:
            msg = f"{spec['domain']} already belongs to another company."
            raise CommandError(msg)

    with schema_context(spec["schema_name"]):
        admin = User.objects.filter(email__iexact=_admin_email(spec)).first()
        if admin is None:
            User.objects.create_user(_admin_email(spec), password, role=StaffRole.ADMIN)
        else:
            admin.role = StaffRole.ADMIN
            admin.set_password(password)
            admin.save()

        for full_name, email, has_login in CLIENTS:
            if Client.objects.filter(email__iexact=email).exists():
                continue
            client_user = None
            if has_login:
                client_user, _created = ClientUser.objects.get_or_create(email=email)
            Client.objects.create(
                full_name=full_name,
                email=email,
                client_user=client_user,
            )

        # Consent wording is immutable per version. Seed it once per company.
        if not ConsentTemplate.objects.exists():
            _ensure_consent(spec["name"])
