from django.db.models import TextChoices
from django.utils.translation import gettext_lazy as _


class StaffRole(TextChoices):
    ADMIN = "admin", _("Admin")
    SUPER_ADMIN = "super_admin", _("Super Admin")
    BACKEND_ADMIN = "backend_admin", _("Backend Admin")


def _role(user: object) -> str | None:
    return getattr(user, "role", None)


def is_admin(user: object) -> bool:
    """Customer admin inside one child."""
    if not getattr(user, "is_authenticated", False):
        return False
    return _role(user) == StaffRole.ADMIN


def is_super_admin(user: object) -> bool:
    """Customer super admin inside one child.

    Django's `is_superuser` flag does not count. That flag is a backend admin.
    """
    if not getattr(user, "is_authenticated", False):
        return False
    return _role(user) == StaffRole.SUPER_ADMIN


def is_backend_admin(user: object) -> bool:
    """Public overseer. Not a tenant user and never `Client.admin`.

    An explicit tenant role wins over `is_superuser`, so a child super admin
    who also has the Django flag stays a super admin.
    """
    if not getattr(user, "is_authenticated", False):
        return False
    if _role(user) == StaffRole.BACKEND_ADMIN:
        return True
    if _role(user) in {StaffRole.ADMIN, StaffRole.SUPER_ADMIN}:
        return False
    return bool(getattr(user, "is_superuser", False))


def is_tenant_staff(user: object) -> bool:
    """Admin or super admin of one child."""
    return is_admin(user) or is_super_admin(user)


def can_sign_in(user: object) -> bool:
    return is_tenant_staff(user) or is_backend_admin(user)
