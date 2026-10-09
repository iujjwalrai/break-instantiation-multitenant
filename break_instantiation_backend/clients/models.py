from uuid import uuid4

from django.conf import settings
from django.db.models import PROTECT
from django.db.models import CharField
from django.db.models import DateTimeField
from django.db.models import EmailField
from django.db.models import ForeignKey
from django.db.models import Index
from django.db.models import OneToOneField
from django.db.models import TextChoices
from django.db.models import UniqueConstraint
from django.db.models import UUIDField
from django.db.models.functions import Lower
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from model_utils.models import TimeStampedModel

from break_instantiation_backend.tokens import TokenBase


class ClientUser(TimeStampedModel):
    """Login identity for a client. Created when they redeem an invite.

    Not `AUTH_USER_MODEL`. Staff stay on `users.User`. There is no password.
    """

    is_authenticated = True

    id = UUIDField(primary_key=True, default=uuid4, editable=False)
    email = EmailField(_("email address"), unique=True)
    disabled_at = DateTimeField(_("disabled at"), null=True, blank=True)

    class Meta:
        constraints = [
            UniqueConstraint(
                Lower("email"),
                name="clients_clientuser_email_ci_unique",
            ),
        ]

    def __str__(self) -> str:
        return str(self.email)

    def save(self, *args, **kwargs):
        if self.email:
            self.email = str(self.email).lower()
        super().save(*args, **kwargs)


class Client(TimeStampedModel):
    """Profile staff create before a login exists.

    `email` is the address the invite is sent to. `ClientUser.email` is
    copied from it at redemption and may diverge later.
    """

    id = UUIDField(primary_key=True, default=uuid4, editable=False)
    full_name = CharField(_("full name"), max_length=255)
    email = EmailField(_("email address"), unique=True)
    client_user = OneToOneField(
        ClientUser,
        on_delete=PROTECT,
        null=True,
        blank=True,
        related_name="client",
    )
    admin = ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=PROTECT,
        null=True,
        blank=True,
        related_name="assigned_clients",
    )

    class Meta:
        constraints = [
            UniqueConstraint(
                Lower("email"),
                name="clients_client_email_ci_unique",
            ),
        ]

    def __str__(self) -> str:
        return str(self.full_name)

    def save(self, *args, **kwargs):
        if self.email:
            self.email = str(self.email).lower()
        super().save(*args, **kwargs)


class ClientPortalInviteStatus(TextChoices):
    SENT = "sent", _("Sent")
    OPENED = "opened", _("Opened")
    ACCEPTED = "accepted", _("Accepted")
    EXPIRED = "expired", _("Expired")


class ClientPortalInvite(TokenBase):
    """One-time link that creates the `ClientUser` on redemption."""

    invited_email = EmailField(_("invited email"))
    invited_by = ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=PROTECT,
        related_name="client_portal_invites_sent",
    )
    target_client = ForeignKey(
        Client,
        on_delete=PROTECT,
        related_name="portal_invites",
    )
    opened_at = DateTimeField(_("opened at"), null=True, blank=True)

    def __str__(self) -> str:
        return str(self.invited_email)

    def save(self, *args, **kwargs):
        if self.invited_email:
            self.invited_email = str(self.invited_email).lower()
        super().save(*args, **kwargs)

    @property
    def status(self) -> ClientPortalInviteStatus:
        """Accepted and expired win over opened. A used invite stays accepted."""
        if self.used:
            return ClientPortalInviteStatus.ACCEPTED
        if self.expires_at <= timezone.now():
            return ClientPortalInviteStatus.EXPIRED
        if self.opened_at is not None:
            return ClientPortalInviteStatus.OPENED
        return ClientPortalInviteStatus.SENT


class MagicLoginToken(TokenBase):
    """One-time link for a client who already has a `ClientUser`."""

    client_user = ForeignKey(
        ClientUser,
        on_delete=PROTECT,
        related_name="magic_login_tokens",
    )

    def __str__(self) -> str:
        return str(self.client_user)


class ClientSession(TimeStampedModel):
    """Sliding idle session. No absolute cap. Raw token is never stored."""

    id = UUIDField(primary_key=True, default=uuid4, editable=False)
    token_hash = CharField(max_length=64, unique=True)
    client_user = ForeignKey(
        ClientUser,
        on_delete=PROTECT,
        related_name="sessions",
    )
    expires_at = DateTimeField()
    revoked_at = DateTimeField(null=True, blank=True)
    last_used_at = DateTimeField()

    class Meta:
        indexes = [
            Index(fields=["client_user", "revoked_at"]),
        ]

    def __str__(self) -> str:
        return str(self.client_user)
