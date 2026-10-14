from django.db import connection
from django.db.models import TextChoices
from django.utils.translation import gettext_lazy as _
from django_tenants.utils import get_public_schema_name


class StaffRole(TextChoices):
    ADMIN = "admin", _("Admin")
    BACKEND_ADMIN = "backend_admin", _("Backend Admin")


def _role(user: object) -> str | None:
    return getattr(user, "role", None)


def is_admin(user: object) -> bool:
    """Customer admin inside one child. The only customer role."""
    if not getattr(user, "is_authenticated", False):
        return False
    return _role(user) == StaffRole.ADMIN


def is_backend_admin(user: object) -> bool:
    """Public overseer. Not a tenant user.

    An explicit admin role wins over `is_superuser`, so a customer admin
    who also has the Django flag stays an admin. A blank role with
    `is_superuser` is a backend admin.
    """
    if not getattr(user, "is_authenticated", False):
        return False
    if _role(user) == StaffRole.BACKEND_ADMIN:
        return True
    if _role(user) == StaffRole.ADMIN:
        return False
    if not getattr(user, "is_superuser", False):
        return False
    # A blank role with is_superuser counts only on a public row.
    home = getattr(user, "_staff_schema", None)
    if home is not None:
        return home == get_public_schema_name()
    schema_name = getattr(connection, "schema_name", None)
    return schema_name == get_public_schema_name()


def is_tenant_staff(user: object) -> bool:
    """Customer admin of one child."""
    return is_admin(user)


def can_sign_in(user: object) -> bool:
    return is_tenant_staff(user) or is_backend_admin(user)
