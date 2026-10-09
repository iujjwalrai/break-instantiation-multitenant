from django.db.models import TextChoices
from django.utils.translation import gettext_lazy as _


class StaffRole(TextChoices):
    ADMIN = "admin", _("Admin")
    SUPER_ADMIN = "super_admin", _("Super Admin")


def is_super_admin(user: object) -> bool:
    """Product super admin, or Django's own superuser flag."""
    if not getattr(user, "is_authenticated", False):
        return False
    return bool(
        getattr(user, "is_superuser", False)
        or getattr(user, "role", None) == StaffRole.SUPER_ADMIN,
    )


def is_admin(user: object) -> bool:
    if not getattr(user, "is_authenticated", False):
        return False
    return getattr(user, "role", None) == StaffRole.ADMIN


def is_staff_member(user: object) -> bool:
    return is_admin(user) or is_super_admin(user)
