from typing import ClassVar

from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
from django.db import connection
from django.db.models import CharField
from django.db.models import EmailField
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from django_tenants.utils import get_public_schema_name

from .managers import UserManager
from .roles import StaffRole


class User(AbstractUser):
    """
    Default custom user model for break-instantiation-backend.
    If adding fields that need to be filled at user signup,
    check forms.SignupForm and forms.SocialSignupForms accordingly.
    """

    # First and last name do not cover name patterns around the globe
    name = CharField(_("Name of User"), blank=True, max_length=255)
    first_name = None  # type: ignore[assignment]
    last_name = None  # type: ignore[assignment]
    email = EmailField(_("email address"), unique=True)
    username = None  # type: ignore[assignment]
    # Blank means no product role. `is_superuser` with no tenant role counts
    # as backend admin, not as a customer admin.
    role = CharField(
        _("role"),
        max_length=32,
        choices=StaffRole.choices,
        blank=True,
        default="",
    )

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    objects: ClassVar[UserManager] = UserManager()

    def save(self, *args, **kwargs):
        schema_name = getattr(connection, "schema_name", None)
        schema_name = schema_name or get_public_schema_name()
        public = get_public_schema_name()
        if self.role == StaffRole.BACKEND_ADMIN and schema_name != public:
            msg = "Backend admin accounts are stored on the public schema."
            raise ValidationError(msg)
        if self.role == StaffRole.ADMIN and schema_name == public:
            msg = "Admin accounts are stored in a child schema."
            raise ValidationError(msg)
        super().save(*args, **kwargs)

    def get_absolute_url(self) -> str:
        """Get URL for user's detail view.

        Returns:
            str: URL for user detail.

        """
        return reverse("users:detail", kwargs={"pk": self.id})


class Admin(User):
    """Admin rows in Django admin. Same table as ``User``."""

    class Meta:
        proxy = True
        verbose_name = _("Admin")
        verbose_name_plural = _("Admins")


class BackendAdmin(User):
    """Backend admin rows in Django admin. Same table as ``User``."""

    class Meta:
        proxy = True
        verbose_name = _("Backend admin")
        verbose_name_plural = _("Backend admins")
