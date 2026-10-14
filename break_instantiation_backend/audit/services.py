from __future__ import annotations

import logging
import typing

from django.conf import settings
from django.db import connection
from django_tenants.utils import get_public_schema_name

from break_instantiation_backend.users.models import User

from .models import AdminActivityEvent
from .models import AssessmentActivityEvent
from .models import AuthEvent
from .models import ClientActivityEvent

logger = logging.getLogger(__name__)

if typing.TYPE_CHECKING:
    from django.http import HttpRequest

    from break_instantiation_backend.clients.models import Client
    from break_instantiation_backend.clients.models import ClientUser

    from .models import AdminActivityEventType
    from .models import AssessmentActivityEventType
    from .models import AuthEventType
    from .models import ClientActivityEventType

USER_AGENT_MAX_LENGTH = 512


def _on_child_schema() -> bool:
    """Audit tables live in the child. Public keeps the child list and admins."""
    return connection.schema_name != get_public_schema_name()


def _local_user(user: User) -> User | None:
    """The user row in this schema, or None when they live on public."""
    home = getattr(user, "_staff_schema", None)
    if home is not None and home != connection.schema_name:
        return None
    if not user.pk:
        return None
    if User.objects.filter(pk=user.pk, email__iexact=user.email).exists():
        return user
    return None


def _client_ip(request: HttpRequest) -> str | None:
    """Address of whoever connected for `request`.

    Trusts the last `X-Forwarded-For` hop only when
    `settings.TRUST_X_FORWARDED_FOR_IP` is on. That hop is what the
    reverse proxy observed. Entries to its left are client-supplied.
    Off, or with the header absent, uses `REMOTE_ADDR`.
    """
    if settings.TRUST_X_FORWARDED_FOR_IP:
        forwarded_for = request.headers.get("x-forwarded-for")
        if forwarded_for:
            return forwarded_for.rsplit(",", 1)[-1].strip()
    return request.META.get("REMOTE_ADDR")


def record_event(  # noqa: PLR0913
    event_type: AuthEventType,
    *,
    user: User | None = None,
    client_user: ClientUser | None = None,
    request: HttpRequest | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> AuthEvent | None:
    """Create an `AuthEvent`. Exactly one identity is required."""
    if (user is None) == (client_user is None):
        msg = "record_event requires exactly one of `user` or `client_user`."
        raise ValueError(msg)
    if not _on_child_schema():
        logger.info("Auth event %s on public is not stored.", event_type)
        return None

    if request is not None:
        if ip_address is None:
            ip_address = _client_ip(request)
        if user_agent is None:
            user_agent = request.headers.get("user-agent")

    if user_agent is not None:
        user_agent = user_agent[:USER_AGENT_MAX_LENGTH]

    local_user = _local_user(user) if user is not None else None
    external_actor_email = ""
    if user is not None and local_user is None:
        external_actor_email = user.email
    return AuthEvent.objects.create(
        event_type=event_type,
        user=local_user,
        client_user=client_user,
        external_actor_email=external_actor_email,
        ip_address=ip_address,
        user_agent=user_agent,
    )


def record_activity_event(
    event_type: AdminActivityEventType,
    *,
    actor: User,
    target: User | None = None,
    previous_role_name: str = "",
    new_role_name: str = "",
) -> AdminActivityEvent | None:
    """Create an `AdminActivityEvent`."""
    if not _on_child_schema():
        logger.info("Admin activity %s on public is not stored.", event_type)
        return None
    local_actor = _local_user(actor)
    return AdminActivityEvent.objects.create(
        event_type=event_type,
        actor_user=local_actor,
        external_actor_email="" if local_actor is not None else actor.email,
        target_user=target,
        previous_role_name=previous_role_name,
        new_role_name=new_role_name,
    )


def record_client_event(
    event_type: ClientActivityEventType,
    *,
    actor: User,
    client: Client,
    changes: dict | None = None,
) -> ClientActivityEvent | None:
    """Create a `ClientActivityEvent`. `changes` defaults to `{}`."""
    if not _on_child_schema():
        logger.info("Client activity %s on public is not stored.", event_type)
        return None
    local_actor = _local_user(actor)
    return ClientActivityEvent.objects.create(
        actor_user=local_actor,
        external_actor_email="" if local_actor is not None else actor.email,
        client=client,
        event_type=event_type,
        changes=changes or {},
    )


def record_assessment_event(
    event_type: AssessmentActivityEventType,
    *,
    client: Client,
) -> AssessmentActivityEvent:
    """Create an `AssessmentActivityEvent`."""
    return AssessmentActivityEvent.objects.create(
        client=client,
        event_type=event_type,
    )
