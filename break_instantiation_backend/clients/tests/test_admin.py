from http import HTTPStatus

import pytest
from django.urls import reverse

from break_instantiation_backend.audit.models import AuthEvent
from break_instantiation_backend.audit.models import AuthEventType
from break_instantiation_backend.audit.models import ClientActivityEvent
from break_instantiation_backend.audit.models import ClientActivityEventType
from break_instantiation_backend.clients.models import Client
from break_instantiation_backend.clients.models import ClientPortalInvite
from break_instantiation_backend.clients.models import ClientUser
from break_instantiation_backend.clients.tests.factories import ClientFactory
from break_instantiation_backend.clients.tests.factories import ClientUserFactory
from break_instantiation_backend.tokens import hash_token

pytestmark = pytest.mark.django_db


def test_admin_creates_and_edits_a_client(admin_client):
    added = admin_client.post(
        reverse("admin:clients_client_add"),
        data={"full_name": "Ada Lovelace", "email": "Ada@Example.com"},
    )
    assert added.status_code == HTTPStatus.FOUND
    profile = Client.objects.get(email="ada@example.com")
    assert profile.full_name == "Ada Lovelace"
    assert ClientActivityEvent.objects.filter(
        client=profile,
        event_type=ClientActivityEventType.CLIENT_CREATED,
    ).exists()

    edited = admin_client.post(
        reverse("admin:clients_client_change", kwargs={"object_id": profile.pk}),
        data={"full_name": "Ada", "email": "ada@example.com"},
    )
    assert edited.status_code == HTTPStatus.FOUND
    profile.refresh_from_db()
    assert profile.full_name == "Ada"
    event = ClientActivityEvent.objects.get(
        client=profile,
        event_type=ClientActivityEventType.CLIENT_UPDATED,
    )
    assert event.changes == {
        "full_name": {"old": "Ada Lovelace", "new": "Ada"},
    }


def test_client_delete_is_refused(admin_client):
    profile = ClientFactory.create()
    denied = admin_client.post(
        reverse("admin:clients_client_delete", kwargs={"object_id": profile.pk}),
        data={"post": "yes"},
    )
    assert denied.status_code == HTTPStatus.FORBIDDEN
    assert Client.objects.filter(pk=profile.pk).exists()


def test_issue_invite_without_a_token_hash(admin_client, mailoutbox):
    profile = ClientFactory.create(email="ada@example.com", full_name="Ada")
    response = admin_client.post(
        reverse("admin:clients_clientportalinvite_add"),
        data={"target_client": str(profile.pk)},
    )
    assert response.status_code == HTTPStatus.FOUND
    invite = ClientPortalInvite.objects.get(target_client=profile)
    assert invite.invited_email == "ada@example.com"
    assert len(invite.token_hash) == len(hash_token("placeholder"))
    assert invite.invited_by.email == "admin@example.com"
    assert len(mailoutbox) == 1
    assert "token_hash" not in mailoutbox[0].body


def test_invite_form_rejects_a_client_who_already_has_a_login(admin_client):
    login = ClientUserFactory.create()
    profile = ClientFactory.create(client_user=login)
    response = admin_client.post(
        reverse("admin:clients_clientportalinvite_add"),
        data={"target_client": str(profile.pk)},
    )
    assert response.status_code == HTTPStatus.OK
    assert not ClientPortalInvite.objects.filter(target_client=profile).exists()


def test_disable_and_reenable_portal_access(admin_client):
    client_user = ClientUserFactory.create()
    url = reverse("admin:clients_clientuser_changelist")
    disabled = admin_client.post(
        url,
        data={
            "action": "disable_portal_access",
            "_selected_action": [str(client_user.pk)],
        },
    )
    assert disabled.status_code == HTTPStatus.FOUND
    client_user.refresh_from_db()
    assert client_user.disabled_at is not None
    assert AuthEvent.objects.filter(
        client_user=client_user,
        event_type=AuthEventType.LOGOUT,
    ).exists()

    reenabled = admin_client.post(
        url,
        data={
            "action": "reenable_portal_access",
            "_selected_action": [str(client_user.pk)],
        },
    )
    assert reenabled.status_code == HTTPStatus.FOUND
    client_user.refresh_from_db()
    assert client_user.disabled_at is None


def test_magic_login_token_cannot_be_added_by_hand(admin_client):
    response = admin_client.get(reverse("admin:clients_magiclogintoken_add"))
    assert response.status_code == HTTPStatus.FORBIDDEN


def test_client_user_cannot_be_deleted(admin_client):
    client_user = ClientUserFactory.create()
    denied = admin_client.post(
        reverse(
            "admin:clients_clientuser_delete",
            kwargs={"object_id": client_user.pk},
        ),
        data={"post": "yes"},
    )
    assert denied.status_code == HTTPStatus.FORBIDDEN
    assert ClientUser.objects.filter(pk=client_user.pk).exists()
