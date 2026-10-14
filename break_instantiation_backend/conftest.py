from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from django.db import connection
from django_tenants.utils import get_tenant_domain_model
from django_tenants.utils import get_tenant_model

from break_instantiation_backend.children.models import ChildStatus
from break_instantiation_backend.users.roles import StaffRole
from break_instantiation_backend.users.tests.factories import UserFactory

if TYPE_CHECKING:
    from break_instantiation_backend.users.models import User

TEST_CHILDREN = (
    ("public", "Public", "public.test", ChildStatus.LIVE, False, ""),
    ("test", "Test", "testserver", ChildStatus.LIVE, True, "http://localhost:3001"),
    ("ej", "EJ", "ej.test", ChildStatus.LIVE, True, "http://ej.localhost:3001"),
    (
        "break",
        "Break",
        "break.test",
        ChildStatus.LIVE,
        True,
        "http://break.localhost:3001",
    ),
    ("draft", "Draft", "draft.test", ChildStatus.DRAFT, True, ""),
)


@pytest.fixture(scope="session")
def django_db_setup(django_db_setup, django_db_blocker):
    """Migrate public, then the child schemas the tests sign in to."""
    with django_db_blocker.unblock():
        connection.set_schema_to_public()
        tenant_model = get_tenant_model()
        domain_model = get_tenant_domain_model()
        for schema_name, name, domain, status, create_schema, site in TEST_CHILDREN:
            tenant = tenant_model.objects.filter(schema_name=schema_name).first()
            if tenant is None:
                tenant = tenant_model(
                    schema_name=schema_name,
                    name=name,
                    status=status,
                    client_site_url=site,
                )
                if not create_schema:
                    tenant.auto_create_schema = False
                tenant.save(verbosity=0)
            elif (
                tenant.name != name
                or tenant.status != status
                or tenant.client_site_url != site
            ):
                tenant.name = name
                tenant.status = status
                tenant.client_site_url = site
                tenant.save(verbosity=0)
            domain_model.objects.get_or_create(
                domain=domain,
                defaults={"tenant": tenant, "is_primary": True},
            )
        connection.set_schema_to_public()


@pytest.fixture(autouse=True)
def _enter_test_child(db):
    """Existing tests run inside the `test` child, on host `testserver`."""
    tenant = get_tenant_model().objects.get(schema_name="test")
    connection.set_tenant(tenant)
    yield
    connection.set_schema_to_public()


@pytest.fixture(autouse=True)
def _media_storage(settings, tmpdir) -> None:
    settings.MEDIA_ROOT = tmpdir.strpath


@pytest.fixture
def user(_enter_test_child) -> User:
    return UserFactory.create()


@pytest.fixture
def admin_user(_enter_test_child, django_user_model) -> User:
    """Tenant staff for Django admin. An explicit admin, even with the flag."""
    return django_user_model.objects.create_user(
        "admin@example.com",
        "password",
        role=StaffRole.ADMIN,
        is_staff=True,
        is_superuser=True,
    )
