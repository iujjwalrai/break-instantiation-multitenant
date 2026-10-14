from uuid import uuid4

from django.db.models import PROTECT
from django.db.models import CharField
from django.db.models import CheckConstraint
from django.db.models import DateTimeField
from django.db.models import ForeignKey
from django.db.models import GenericIPAddressField
from django.db.models import Index
from django.db.models import JSONField
from django.db.models import Model
from django.db.models import Q
from django.db.models import TextChoices
from django.db.models import UUIDField
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


class AuthEventType(TextChoices):
    LOGIN_SUCCESS = "login_success", _("Login success")
    LOGIN_FAILURE = "login_failure", _("Login failure")
    MAGIC_LINK_SENT = "magic_link_sent", _("Magic link sent")
    MAGIC_LINK_EXPIRED = "magic_link_expired", _("Magic link expired")
    INVITE_SENT = "invite_sent", _("Invite sent")
    INVITE_REDEEMED = "invite_redeemed", _("Invite redeemed")
    LOGOUT = "logout", _("Logout")


class AuthEvent(Model):
    """Append-only authentication event.

    Exactly one identity is set: `user`, `client_user`, or
    `external_actor_email`. The email is a public overseer acting in this
    child. Their row stays on `public`, so this table does not foreign-key
    across schemas. A failed login for an email with no account is not
    stored here.
    """

    id = UUIDField(primary_key=True, default=uuid4, editable=False)
    user = ForeignKey(
        "users.User",
        on_delete=PROTECT,
        null=True,
        blank=True,
        related_name="auth_events",
    )
    client_user = ForeignKey(
        "clients.ClientUser",
        on_delete=PROTECT,
        null=True,
        blank=True,
        related_name="auth_events",
    )
    external_actor_email = CharField(max_length=254, blank=True, default="")
    event_type = CharField(max_length=32, choices=AuthEventType)
    ip_address = GenericIPAddressField(null=True, blank=True)
    user_agent = CharField(max_length=512, null=True, blank=True)  # noqa: DJ001
    occurred_at = DateTimeField(default=timezone.now)

    class Meta:
        constraints = [
            CheckConstraint(
                condition=(
                    Q(
                        user__isnull=False,
                        client_user__isnull=True,
                        external_actor_email="",
                    )
                    | Q(
                        user__isnull=True,
                        client_user__isnull=False,
                        external_actor_email="",
                    )
                    | (
                        Q(user__isnull=True, client_user__isnull=True)
                        & ~Q(external_actor_email="")
                    )
                ),
                name="audit_authevent_exactly_one_identity",
            ),
        ]
        indexes = [
            Index(fields=["user", "occurred_at"]),
            Index(fields=["client_user", "occurred_at"]),
        ]
        ordering = ["-occurred_at"]

    def __str__(self) -> str:
        return f"{self.event_type} @ {self.occurred_at}"

    def save(self, *args, **kwargs):
        if not self._state.adding:
            msg = "AuthEvent rows are append-only and cannot be updated."
            raise ValueError(msg)
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        msg = "AuthEvent rows are append-only and cannot be deleted."
        raise ValueError(msg)


class AdminActivityEventType(TextChoices):
    USER_CREATED = "user_created", _("User created")
    ROLE_CHANGED = "role_changed", _("Role changed")
    USER_DISABLED = "user_disabled", _("User disabled")
    USER_EMAIL_CHANGED = "user_email_changed", _("User email changed")


class AdminActivityEvent(Model):
    """Append-only staff-management action.

    `previous_role_name` and `new_role_name` are text snapshots. A later
    rename of a role does not rewrite what this row said at the time.
    Blank means the user had no role.
    """

    id = UUIDField(primary_key=True, default=uuid4, editable=False)
    actor_user = ForeignKey(
        "users.User",
        on_delete=PROTECT,
        null=True,
        blank=True,
        related_name="admin_activity_events_performed",
    )
    external_actor_email = CharField(max_length=254, blank=True, default="")
    target_user = ForeignKey(
        "users.User",
        on_delete=PROTECT,
        null=True,
        blank=True,
        related_name="admin_activity_events_received",
    )
    event_type = CharField(max_length=32, choices=AdminActivityEventType)
    previous_role_name = CharField(max_length=150, blank=True, default="")
    new_role_name = CharField(max_length=150, blank=True, default="")
    occurred_at = DateTimeField(default=timezone.now)

    class Meta:
        constraints = [
            CheckConstraint(
                condition=(
                    Q(actor_user__isnull=False, external_actor_email="")
                    | (Q(actor_user__isnull=True) & ~Q(external_actor_email=""))
                ),
                name="audit_adminevent_one_actor",
            ),
        ]
        indexes = [
            Index(fields=["target_user", "occurred_at"]),
            Index(fields=["actor_user", "occurred_at"]),
        ]
        ordering = ["-occurred_at"]

    def __str__(self) -> str:
        return f"{self.event_type} @ {self.occurred_at}"

    def save(self, *args, **kwargs):
        if not self._state.adding:
            msg = "AdminActivityEvent rows are append-only and cannot be updated."
            raise ValueError(msg)
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        msg = "AdminActivityEvent rows are append-only and cannot be deleted."
        raise ValueError(msg)


class ClientActivityEventType(TextChoices):
    CLIENT_CREATED = "client_created", _("Client created")
    CLIENT_UPDATED = "client_updated", _("Client updated")
    CONSENT_WITHDRAWN = "consent_withdrawn", _("Consent withdrawn")
    CONSENT_REINSTATED = "consent_reinstated", _("Consent reinstated")


class ClientActivityEvent(Model):
    """Append-only staff action on a client profile.

    `changes` is empty for `CLIENT_CREATED`, `CONSENT_WITHDRAWN`, and
    `CONSENT_REINSTATED`. For `CLIENT_UPDATED` it is `{field: {"old": ...,
    "new": ...}}` for `full_name` and `email`. Emails are snapshots, not
    live foreign keys.

    Consent withdrawn and reinstated are staff actions. The client's own
    grant is an `AssessmentActivityEvent`, not a row here.
    """

    id = UUIDField(primary_key=True, default=uuid4, editable=False)
    actor_user = ForeignKey(
        "users.User",
        on_delete=PROTECT,
        null=True,
        blank=True,
        related_name="client_activity_events",
    )
    external_actor_email = CharField(max_length=254, blank=True, default="")
    client = ForeignKey(
        "clients.Client",
        on_delete=PROTECT,
        related_name="activity_events",
    )
    event_type = CharField(max_length=32, choices=ClientActivityEventType)
    changes = JSONField(default=dict, blank=True)
    occurred_at = DateTimeField(default=timezone.now)

    class Meta:
        constraints = [
            CheckConstraint(
                condition=(
                    Q(actor_user__isnull=False, external_actor_email="")
                    | (Q(actor_user__isnull=True) & ~Q(external_actor_email=""))
                ),
                name="audit_clientevent_one_actor",
            ),
        ]
        indexes = [
            Index(
                fields=["client", "occurred_at"],
                name="audit_cae_client_at_idx",
            ),
        ]
        ordering = ["-occurred_at"]

    def __str__(self) -> str:
        return f"{self.event_type} @ {self.occurred_at}"

    def save(self, *args, **kwargs):
        if not self._state.adding:
            msg = "ClientActivityEvent rows are append-only and cannot be updated."
            raise ValueError(msg)
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        msg = "ClientActivityEvent rows are append-only and cannot be deleted."
        raise ValueError(msg)


class AssessmentActivityEventType(TextChoices):
    CONSENT_GRANTED = "consent_granted", _("Consent granted")
    STARTED = "started", _("Started")
    COMPLETED = "completed", _("Completed")
    RESULT_STORED = "result_stored", _("Result stored")
    SCORING_FAILED = "scoring_failed", _("Scoring failed")


class AssessmentActivityEvent(Model):
    """Append-only record of a client's questionnaire journey.

    Consent granted, assessment started, assessment completed, and whether
    BREAK stored a score or the scoring call failed. There is no staff
    actor: the client progresses their own assessment, and scoring is a
    system follow-up of completion. Staff withdraw and reinstate live on
    `ClientActivityEvent` instead.

    Keyed by `client`, not assessment: consent can be granted before an
    assessment row exists.
    """

    id = UUIDField(primary_key=True, default=uuid4, editable=False)
    client = ForeignKey(
        "clients.Client",
        on_delete=PROTECT,
        related_name="assessment_activity_events",
    )
    event_type = CharField(max_length=32, choices=AssessmentActivityEventType)
    occurred_at = DateTimeField(default=timezone.now)

    class Meta:
        indexes = [
            Index(
                fields=["client", "occurred_at"],
                name="audit_aae_client_at_idx",
            ),
        ]
        ordering = ["-occurred_at"]

    def __str__(self) -> str:
        return f"{self.event_type} @ {self.occurred_at}"

    def save(self, *args, **kwargs):
        if not self._state.adding:
            msg = "AssessmentActivityEvent rows are append-only and cannot be updated."
            raise ValueError(msg)
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        msg = "AssessmentActivityEvent rows are append-only and cannot be deleted."
        raise ValueError(msg)
