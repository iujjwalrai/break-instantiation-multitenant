from django.db import connection
from django_tenants.utils import get_public_schema_name
from django_tenants.utils import schema_context

from break_instantiation_backend.users.models import User
from break_instantiation_backend.users.roles import StaffRole


def create_public_backend_admin(
    email: str,
    password: str,
    *,
    role: str = StaffRole.BACKEND_ADMIN,
    is_staff: bool = True,
    is_superuser: bool = True,
) -> User:
    """A backend admin row on `public`. Tests use this instead of a child row."""
    with schema_context(get_public_schema_name()):
        user = User.objects.create_user(
            email,
            password,
            role=role,
            is_staff=is_staff,
            is_superuser=is_superuser,
        )
        if connection.schema_name == get_public_schema_name():
            user._staff_schema = get_public_schema_name()  # noqa: SLF001
        return user
