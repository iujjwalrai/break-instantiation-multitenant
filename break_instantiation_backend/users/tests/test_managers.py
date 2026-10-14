from io import StringIO

import pytest
from django.core.management import call_command
from django_tenants.utils import schema_context

from break_instantiation_backend.users.models import User
from break_instantiation_backend.users.roles import StaffRole


@pytest.mark.django_db
class TestUserManager:
    def test_create_user(self):
        user = User.objects.create_user(
            email="john@example.com",
            password="something-r@nd0m!",  # noqa: S106
        )
        assert user.email == "john@example.com"
        assert not user.is_staff
        assert not user.is_superuser
        assert user.check_password("something-r@nd0m!")
        assert user.username is None

    def test_create_superuser(self):
        with schema_context("public"):
            user = User.objects.create_superuser(
                email="admin@example.com",
                password="something-r@nd0m!",  # noqa: S106
            )
            assert user.email == "admin@example.com"
            assert user.is_staff
            assert user.is_superuser
            assert user.role == StaffRole.BACKEND_ADMIN
            assert user.username is None
        assert not User.objects.filter(email="admin@example.com").exists()

    def test_create_superuser_username_ignored(self):
        with schema_context("public"):
            user = User.objects.create_superuser(
                email="test@example.com",
                password="something-r@nd0m!",  # noqa: S106
            )
            assert user.username is None


@pytest.mark.django_db
def test_createsuperuser_command():
    """Ensure createsuperuser command works with our custom manager."""
    out = StringIO()
    with schema_context("public"):
        command_result = call_command(
            "createsuperuser",
            "--email",
            "henry@example.com",
            interactive=False,
            stdout=out,
        )
        user = User.objects.get(email="henry@example.com")
    assert command_result is None
    assert out.getvalue() == "Superuser created successfully.\n"
    assert not user.has_usable_password()
    assert user.role == StaffRole.BACKEND_ADMIN
    assert not User.objects.filter(email="henry@example.com").exists()
