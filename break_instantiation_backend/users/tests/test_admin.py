import contextlib
from http import HTTPStatus
from importlib import reload

import pytest
from django.contrib import admin
from django.contrib.auth.models import AnonymousUser
from django.test import Client
from django.urls import reverse
from django_tenants.utils import schema_context
from pytest_django.asserts import assertRedirects

from break_instantiation_backend.audit.models import AdminActivityEvent
from break_instantiation_backend.audit.models import AdminActivityEventType
from break_instantiation_backend.users.models import User
from break_instantiation_backend.users.roles import StaffRole


class TestUserAdmin:
    def test_changelist(self, admin_client):
        url = reverse("admin:users_user_changelist")
        response = admin_client.get(url)
        assert response.status_code == HTTPStatus.OK

    def test_search(self, admin_client):
        url = reverse("admin:users_user_changelist")
        response = admin_client.get(url, data={"q": "test"})
        assert response.status_code == HTTPStatus.OK

    def test_add(self, admin_client):
        url = reverse("admin:users_user_add")
        response = admin_client.get(url)
        assert response.status_code == HTTPStatus.OK

        response = admin_client.post(
            url,
            data={
                "email": "new-admin@example.com",
                "name": "New Admin",
                "role": "admin",
                "password1": "My_R@ndom-P@ssw0rd",
                "password2": "My_R@ndom-P@ssw0rd",
            },
        )
        assert response.status_code == HTTPStatus.FOUND
        user = User.objects.get(email="new-admin@example.com")
        assert user.name == "New Admin"
        assert user.role == "admin"

    def test_index_lists_each_role(self, admin_client):
        response = admin_client.get(reverse("admin:index"))
        assert response.status_code == HTTPStatus.OK
        body = response.content.decode()
        assert reverse("admin:users_admin_changelist") in body
        assert reverse("admin:users_backendadmin_changelist") not in body
        assert reverse("admin:users_user_changelist") not in body

    @pytest.mark.parametrize(
        ("url_name", "email", "role", "django_admin"),
        [
            ("admin:users_admin_add", "role-admin@example.com", StaffRole.ADMIN, False),
        ],
    )
    def test_role_add_sets_role(
        self,
        admin_client,
        url_name,
        email,
        role,
        django_admin,
    ):
        url = reverse(url_name)
        response = admin_client.get(url)
        assert response.status_code == HTTPStatus.OK
        assert b'name="role"' not in response.content

        response = admin_client.post(
            url,
            data={
                "email": email,
                "name": "Role User",
                "password1": "My_R@ndom-P@ssw0rd",
                "password2": "My_R@ndom-P@ssw0rd",
            },
        )
        assert response.status_code == HTTPStatus.FOUND
        user = User.objects.get(email=email)
        assert user.role == role
        assert user.is_staff is django_admin
        assert user.is_superuser is django_admin

    def test_public_admin_creates_a_backend_admin(self):
        with schema_context("public"):
            root = User.objects.create_superuser(
                "root-public@example.com",
                "My_R@ndom-P@ssw0rd",
            )
            http = Client(headers={"host": "public.test"})
            http.force_login(root)
            response = http.get(reverse("admin:index"))
            assert response.status_code == HTTPStatus.OK
            body = response.content.decode()
            assert reverse("admin:users_backendadmin_changelist") in body
            assert reverse("admin:users_admin_changelist") not in body
            response = http.post(
                reverse("admin:users_backendadmin_add"),
                data={
                    "email": "role-backend@example.com",
                    "name": "Role User",
                    "password1": "My_R@ndom-P@ssw0rd",
                    "password2": "My_R@ndom-P@ssw0rd",
                },
            )
            assert response.status_code == HTTPStatus.FOUND, response.content
            created = User.objects.get(email="role-backend@example.com")
            assert created.role == StaffRole.BACKEND_ADMIN
            assert created.is_staff is True
            assert created.is_superuser is True
        assert not User.objects.filter(email="role-backend@example.com").exists()

    def test_role_changelist_is_limited(self, admin_client):
        User.objects.create_user(
            "listed-admin@example.com",
            "My_R@ndom-P@ssw0rd",
            role=StaffRole.ADMIN,
        )
        response = admin_client.get(reverse("admin:users_admin_changelist"))
        assert response.status_code == HTTPStatus.OK
        body = response.content.decode()
        assert "listed-admin@example.com" in body

    def test_role_change_edits_profile_and_disables(self, admin_client):
        user = User.objects.create_user(
            "editable-admin@example.com",
            "My_R@ndom-P@ssw0rd",
            role=StaffRole.ADMIN,
            name="Before",
        )
        url = reverse("admin:users_admin_change", kwargs={"object_id": user.pk})
        response = admin_client.post(
            url,
            data={
                "email": "renamed-admin@example.com",
                "name": "After",
            },
        )
        assert response.status_code == HTTPStatus.FOUND, response.content
        user.refresh_from_db()
        assert user.email == "renamed-admin@example.com"
        assert user.name == "After"
        assert user.is_active is False
        assert user.role == StaffRole.ADMIN
        assert AdminActivityEvent.objects.filter(
            target_user=user,
            event_type=AdminActivityEventType.USER_EMAIL_CHANGED,
        ).exists()
        assert AdminActivityEvent.objects.filter(
            target_user=user,
            event_type=AdminActivityEventType.USER_DISABLED,
        ).exists()
        denied = admin_client.post(
            reverse("admin:users_admin_delete", kwargs={"object_id": user.pk}),
            data={"post": "yes"},
        )
        assert denied.status_code == HTTPStatus.FORBIDDEN
        assert User.objects.filter(pk=user.pk).exists()

    def test_view_user(self, admin_client):
        user = User.objects.get(email="admin@example.com")
        url = reverse("admin:users_user_change", kwargs={"object_id": user.pk})
        response = admin_client.get(url)
        assert response.status_code == HTTPStatus.OK

    @pytest.fixture
    def _force_allauth(self, settings):
        settings.DJANGO_ADMIN_FORCE_ALLAUTH = True
        # Reload the admin module to apply the setting change
        import break_instantiation_backend.users.admin as users_admin  # noqa: PLC0415

        with contextlib.suppress(admin.sites.AlreadyRegistered):  # type: ignore[attr-defined]
            reload(users_admin)

    @pytest.mark.django_db
    @pytest.mark.usefixtures("_force_allauth")
    def test_allauth_login(self, rf, settings):
        request = rf.get("/fake-url")
        request.user = AnonymousUser()
        response = admin.site.login(request)

        # The `admin` login view should redirect to the `allauth` login view
        target_url = reverse(settings.LOGIN_URL) + "?next=" + request.path
        assertRedirects(response, target_url, fetch_redirect_response=False)
