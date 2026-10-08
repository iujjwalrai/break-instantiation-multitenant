from __future__ import annotations

import hashlib
import secrets
import typing
from uuid import uuid4

from django.db import transaction
from django.db.models import BooleanField
from django.db.models import CharField
from django.db.models import DateTimeField
from django.db.models import UUIDField
from django.utils import timezone
from model_utils.models import TimeStampedModel

if typing.TYPE_CHECKING:
    from django.db.models import QuerySet


def generate_token() -> str:
    """High-entropy raw token for a one-time link.

    Handed to the caller once (embedded in an emailed URL) and never stored.
    """
    return secrets.token_urlsafe(32)


def hash_token(raw_token: str) -> str:
    """SHA-256 digest of a raw token, for storage and lookup.

    The raw value is already 32 bytes of randomness, so a slow password hash
    buys nothing. A fast digest is what makes an exact lookup possible.
    """
    return hashlib.sha256(raw_token.encode()).hexdigest()


class TokenBase(TimeStampedModel):
    """One-time expiring token. Only `hash_token(raw)` is stored.

    Abstract, so it needs no app of its own.
    """

    id = UUIDField(primary_key=True, default=uuid4, editable=False)
    token_hash = CharField(max_length=64, unique=True)
    expires_at = DateTimeField()
    used = BooleanField(default=False)
    used_at = DateTimeField(null=True, blank=True)

    class Meta:
        abstract = True


class TokenError(Exception):
    """Base for `verify` / `redeem` failures."""


class TokenInvalidError(TokenError):
    """No matching row, or the matched row is already used."""


class TokenExpiredError(TokenError):
    """Matched an unused row whose `expires_at` has passed."""


def verify[TokenT: TokenBase](model_cls: type[TokenT], raw_token: str) -> TokenT:
    """Look up `raw_token` without consuming it."""
    try:
        row = model_cls.objects.get(  # type: ignore[attr-defined]
            token_hash=hash_token(raw_token),
        )
    except model_cls.DoesNotExist as exc:
        msg = "Token not found."
        raise TokenInvalidError(msg) from exc
    if row.used:
        msg = "Token has already been used."
        raise TokenInvalidError(msg)
    if row.expires_at <= timezone.now():
        msg = "Token has expired."
        raise TokenExpiredError(msg)
    return row


def redeem[TokenT: TokenBase](model_cls: type[TokenT], raw_token: str) -> TokenT:
    """Consume the row for `raw_token`.

    `used` and `expires_at` are checked after `select_for_update`, not in the
    filter, so "already used" and "expired" stay distinct. The lock makes two
    concurrent redemptions mutually exclusive.
    """
    with transaction.atomic():
        try:
            row = model_cls.objects.select_for_update().get(  # type: ignore[attr-defined]
                token_hash=hash_token(raw_token),
            )
        except model_cls.DoesNotExist as exc:
            msg = "Token not found."
            raise TokenInvalidError(msg) from exc
        if row.used:
            msg = "Token has already been used."
            raise TokenInvalidError(msg)
        if row.expires_at <= timezone.now():
            msg = "Token has expired."
            raise TokenExpiredError(msg)
        row.used = True
        row.used_at = timezone.now()
        row.save(update_fields=["used", "used_at", "modified"])
    return row


def expire_unused[TokenT: TokenBase](queryset: QuerySet[TokenT]) -> int:
    """Hard-expire every unused row in `queryset`. Returns the count touched."""
    return queryset.filter(used=False).update(expires_at=timezone.now())
