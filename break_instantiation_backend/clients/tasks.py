import logging

from celery import shared_task
from django.conf import settings

from break_instantiation_backend.mail import build_action_link
from break_instantiation_backend.mail import send_action_email

logger = logging.getLogger(__name__)


@shared_task()
def send_portal_invite_email(to_email: str, raw_token: str, base_url: str) -> None:
    """Email the link that creates a `ClientUser`. Never log `raw_token`."""
    link = build_action_link(
        base_url=base_url,
        path="/invite",
        raw_token=raw_token,
    )
    try:
        send_action_email(
            to_email=to_email,
            subject="You've been invited",
            template="client_portal_invite",
            link=link,
            expires_in=settings.CLIENT_PORTAL_INVITE_TTL,
        )
    except Exception:
        logger.exception("Portal invite email to %s failed", to_email)
        raise
    logger.info("Portal invite email sent to %s", to_email)


@shared_task()
def send_magic_login_email(to_email: str, raw_token: str, base_url: str) -> None:
    """Email a sign-in link for an existing `ClientUser`. Never log `raw_token`."""
    link = build_action_link(
        base_url=base_url,
        path="/magic-login",
        raw_token=raw_token,
    )
    try:
        send_action_email(
            to_email=to_email,
            subject="Your sign-in link",
            template="client_magic_login",
            link=link,
            expires_in=settings.MAGIC_LOGIN_TOKEN_TTL,
        )
    except Exception:
        logger.exception("Magic login email to %s failed", to_email)
        raise
    logger.info("Magic login email sent to %s", to_email)
