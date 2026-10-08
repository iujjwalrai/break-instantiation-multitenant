from uuid import uuid4

from django.db.models import PROTECT
from django.db.models import CharField
from django.db.models import DateTimeField
from django.db.models import EmailField
from django.db.models import ForeignKey
from django.db.models import Index
from django.db.models import UniqueConstraint
from django.db.models import UUIDField
from django.db.models.functions import Lower
from django.utils.translation import gettext_lazy as _
from model_utils.models import TimeStampedModel

from break_instantiation_backend.tokens import TokenBase


class Respondent(TimeStampedModel):
    """Login identity for someone taking a questionnaire.

    Not `AUTH_USER_MODEL`. Staff stay on `users.User`. This object is what
    `RespondentSessionAuthentication` puts on `request.user`.

    `is_authenticated` is a class attribute, not a column, so DRF's
    `IsAuthenticated` accepts it. There is no password.
    """

    is_authenticated = True

    id = UUIDField(primary_key=True, default=uuid4, editable=False)
    email = EmailField(_("email address"), unique=True)
    # Null means active. Set only when access is cut off.
    disabled_at = DateTimeField(_("disabled at"), null=True, blank=True)

    class Meta:
        constraints = [
            UniqueConstraint(
                Lower("email"),
                name="respondents_respondent_email_ci_unique",
            ),
        ]

    def __str__(self) -> str:
        return str(self.email)

    def save(self, *args, **kwargs):
        if self.email:
            self.email = str(self.email).lower()
        super().save(*args, **kwargs)


class MagicLoginToken(TokenBase):
    """One-time link for a returning respondent. Lives 15 minutes."""

    respondent = ForeignKey(
        Respondent,
        on_delete=PROTECT,
        related_name="magic_login_tokens",
    )

    def __str__(self) -> str:
        return str(self.respondent)


class RespondentSession(TimeStampedModel):
    """Sliding idle session. No absolute cap. Raw token is never stored."""

    id = UUIDField(primary_key=True, default=uuid4, editable=False)
    token_hash = CharField(max_length=64, unique=True)
    respondent = ForeignKey(
        Respondent,
        on_delete=PROTECT,
        related_name="sessions",
    )
    expires_at = DateTimeField()
    revoked_at = DateTimeField(null=True, blank=True)
    last_used_at = DateTimeField()

    class Meta:
        indexes = [
            Index(fields=["respondent", "revoked_at"]),
        ]

    def __str__(self) -> str:
        return str(self.respondent)
