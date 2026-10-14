"""Tokenized auth email: one short-lived link, plain text and HTML.

No open-tracking pixel and no click-tracking redirect. The link is the
credential. No recipient name in the message or in the Celery arguments.
"""

from __future__ import annotations

import typing
from urllib.parse import urlencode

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string

from break_instantiation_backend.children.models import Child
from break_instantiation_backend.children.schema import current_look

if typing.TYPE_CHECKING:
    from datetime import timedelta

AUTO_RESPONSE_HEADERS = {
    "Auto-Submitted": "auto-generated",
    "X-Auto-Response-Suppress": "All",
}

_TTL_UNITS = ((86400, "day"), (3600, "hour"), (60, "minute"))


def humanize_ttl(delta: timedelta) -> str:
    """Largest unit the lifetime divides into evenly."""
    total = int(delta.total_seconds())
    for seconds, unit in _TTL_UNITS:
        if total >= seconds and total % seconds == 0:
            count = total // seconds
            return f"{count} {unit}" if count == 1 else f"{count} {unit}s"
    return f"{total} second" if total == 1 else f"{total} seconds"


def email_wordmark() -> str:
    """The company's own name inside a child. The setting is the fallback."""
    try:
        name = current_look()["name"]
    except RuntimeError, Child.DoesNotExist:
        name = ""
    return name or settings.CLIENT_EMAIL_WORDMARK


def build_action_link(*, base_url: str, path: str, raw_token: str) -> str:
    """SPA link. Token is query-encoded so `+` or `/` cannot break it."""
    query = urlencode({"token": raw_token})
    return f"{base_url.rstrip('/')}{path}?{query}"


def send_action_email(
    *,
    to_email: str,
    subject: str,
    template: str,
    link: str,
    expires_in: timedelta,
) -> None:
    """Render `emails/{template}.txt` and `.html` and send them as one message."""
    context = {
        "link": link,
        "expires_in_display": humanize_ttl(expires_in),
        "security_contact": settings.SECURITY_CONTACT_EMAIL,
        "wordmark": email_wordmark(),
    }
    message = EmailMultiAlternatives(
        subject=subject,
        body=render_to_string(f"emails/{template}.txt", context).strip() + "\n",
        from_email=None,
        to=[to_email],
        headers=AUTO_RESPONSE_HEADERS,
    )
    message.attach_alternative(
        render_to_string(f"emails/{template}.html", context),
        "text/html",
    )
    message.send()
