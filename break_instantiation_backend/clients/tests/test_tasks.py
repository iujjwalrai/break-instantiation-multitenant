import pytest
from django_tenants.utils import schema_context

from break_instantiation_backend.children.models import Child
from break_instantiation_backend.clients.tasks import send_magic_login_email
from break_instantiation_backend.clients.tasks import send_portal_invite_email

pytestmark = pytest.mark.django_db


def test_mail_uses_the_company_client_site(mailoutbox):
    with schema_context("public"):
        Child.objects.filter(schema_name="ej").update(
            client_site_url="http://ej.localhost:3001",
        )
        Child.objects.filter(schema_name="break").update(
            client_site_url="http://break.localhost:3001",
        )

    send_portal_invite_email("ej", "ada@ej.test", "ej-invite")
    send_magic_login_email("break", "ada@break.test", "break-login")

    bodies = [message.body for message in mailoutbox]
    assert any(
        "http://ej.localhost:3001/invite?token=ej-invite" in body for body in bodies
    )
    assert any(
        "http://break.localhost:3001/magic-login?token=break-login" in body
        for body in bodies
    )


def test_mail_refuses_a_company_without_a_client_site(mailoutbox):
    with schema_context("public"):
        Child.objects.filter(schema_name="draft").update(client_site_url="")

    with pytest.raises(RuntimeError, match="draft has no client site URL"):
        send_portal_invite_email("draft", "ada@draft.test", "draft-invite")

    assert mailoutbox == []
