from allauth.account.decorators import secure_admin_login
from django.conf import settings
from django.contrib import admin
from django.contrib.admin.forms import AdminAuthenticationForm
from django.contrib.auth import REDIRECT_FIELD_NAME
from django.contrib.auth import admin as auth_admin
from django.contrib.auth.views import LoginView
from django.db import connection
from django.http import HttpResponseRedirect
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from django_tenants.utils import get_public_schema_name

from break_instantiation_backend.audit.models import AdminActivityEventType
from break_instantiation_backend.audit.models import AuthEventType
from break_instantiation_backend.audit.services import record_activity_event
from break_instantiation_backend.audit.services import record_event

from .forms import StaffRoleCreationForm
from .forms import UserAdminChangeForm
from .forms import UserAdminCreationForm
from .models import Admin
from .models import BackendAdmin
from .models import User
from .roles import StaffRole
from .staff_auth import authenticate_staff
from .staff_auth import login_staff

if settings.DJANGO_ADMIN_FORCE_ALLAUTH:
    # Force the admin sign-in process to go through the django-allauth workflow:
    # https://docs.allauth.org/en/latest/common/admin.html#admin
    admin.autodiscover()
    admin.site.login = secure_admin_login(admin.site.login)  # type: ignore[method-assign]


@admin.register(User)
class UserAdmin(auth_admin.UserAdmin):
    form = UserAdminChangeForm
    add_form = UserAdminCreationForm
    fieldsets = (
        (None, {"fields": ("email", "password")}),
        (_("Personal info"), {"fields": ("name",)}),
        (
            _("Permissions"),
            {
                "fields": (
                    "is_active",
                    "is_staff",
                    "is_superuser",
                    "role",
                    "groups",
                    "user_permissions",
                ),
            },
        ),
        (_("Important dates"), {"fields": ("last_login", "date_joined")}),
    )
    list_display = ["email", "name", "role", "is_staff", "is_superuser"]
    list_filter = ["role", "is_staff", "is_superuser", "is_active"]
    search_fields = ["email", "name"]
    ordering = ["id"]
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": ("email", "name", "role", "password1", "password2"),
            },
        ),
    )

    def get_model_perms(self, request):
        # Kept registered so invite autocompletes can search users.
        # The index shows the two role views instead of this mixed list.
        return {}

    def has_delete_permission(self, request, obj=None):
        # Auth and activity rows protect the user. Disable the account instead.
        return False

    def save_model(self, request, obj, form, change):
        previous = User.objects.get(pk=obj.pk) if change else None
        super().save_model(request, obj, form, change)
        if not getattr(request.user, "is_authenticated", False):
            return
        if previous is None:
            record_activity_event(
                AdminActivityEventType.USER_CREATED,
                actor=request.user,
                target=obj,
                new_role_name=obj.role,
            )
            return
        if previous.role != obj.role:
            record_activity_event(
                AdminActivityEventType.ROLE_CHANGED,
                actor=request.user,
                target=obj,
                previous_role_name=previous.role,
                new_role_name=obj.role,
            )
        if previous.email != obj.email:
            record_activity_event(
                AdminActivityEventType.USER_EMAIL_CHANGED,
                actor=request.user,
                target=obj,
            )
        if previous.is_active and not obj.is_active:
            record_activity_event(
                AdminActivityEventType.USER_DISABLED,
                actor=request.user,
                target=obj,
            )


def _on_public_schema() -> bool:
    return connection.schema_name == get_public_schema_name()


class SchemaRoleAdmin(UserAdmin):
    """Show this role only in the schema where that role is stored."""

    public_only = False

    def _schema_ok(self) -> bool:
        return _on_public_schema() if self.public_only else not _on_public_schema()

    def has_module_permission(self, request):
        return self._schema_ok() and super().has_module_permission(request)

    def has_view_permission(self, request, obj=None):
        return self._schema_ok() and super().has_view_permission(request, obj)

    def has_add_permission(self, request):
        return self._schema_ok() and super().has_add_permission(request)

    def has_change_permission(self, request, obj=None):
        return self._schema_ok() and super().has_change_permission(request, obj)


class StaffRoleAdmin(SchemaRoleAdmin):
    """One Django admin list per role. Saving always writes that role."""

    add_form = StaffRoleCreationForm
    role = ""
    grant_django_admin = False
    filter_horizontal = ()
    readonly_fields = ("last_login", "date_joined")
    list_display = ["email", "name", "is_active"]
    list_filter = ["is_active"]
    ordering = ["email"]
    fieldsets = (
        (None, {"fields": ("email", "password")}),
        (_("Personal info"), {"fields": ("name",)}),
        (_("Status"), {"fields": ("is_active",)}),
        (_("Important dates"), {"fields": ("last_login", "date_joined")}),
    )
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": ("email", "name", "password1", "password2"),
            },
        ),
    )

    def get_model_perms(self, request):
        return admin.ModelAdmin.get_model_perms(self, request)

    def get_queryset(self, request):
        return super().get_queryset(request).filter(role=self.role)

    def save_model(self, request, obj, form, change):
        obj.role = self.role
        if self.grant_django_admin and not change:
            obj.is_staff = True
            obj.is_superuser = True
        super().save_model(request, obj, form, change)


@admin.register(Admin)
class AdminUserAdmin(StaffRoleAdmin):
    role = StaffRole.ADMIN


@admin.register(BackendAdmin)
class BackendAdminUserAdmin(StaffRoleAdmin):
    role = StaffRole.BACKEND_ADMIN
    public_only = True
    grant_django_admin = True
    list_display = ["email", "name", "is_active", "is_staff", "is_superuser"]
    list_filter = ["is_active", "is_staff", "is_superuser"]
    fieldsets = (
        (None, {"fields": ("email", "password")}),
        (_("Personal info"), {"fields": ("name",)}),
        (
            _("Django admin access"),
            {"fields": ("is_active", "is_staff", "is_superuser")},
        ),
        (_("Important dates"), {"fields": ("last_login", "date_joined")}),
    )

    def get_queryset(self, request):
        queryset = admin.ModelAdmin.get_queryset(self, request)
        explicit = queryset.filter(role=StaffRole.BACKEND_ADMIN)
        # A superuser with no tenant role is a backend admin.
        flagged = queryset.filter(role="", is_superuser=True)
        return explicit | flagged


class StaffAdminAuthenticationForm(AdminAuthenticationForm):
    """Django admin sign-in. A public backend admin can use a company host."""

    def clean(self):
        username = self.cleaned_data.get("username")
        password = self.cleaned_data.get("password")
        if username is not None and password:
            account, user = authenticate_staff(self.request, username, password)
            if user is None:
                if account is not None:
                    record_event(
                        AuthEventType.LOGIN_FAILURE,
                        user=account,
                        request=self.request,
                    )
                raise self.get_invalid_login_error()
            self.user_cache = user
            self.confirm_login_allowed(user)
        return self.cleaned_data


class StaffAdminLoginView(LoginView):
    """Same session rule as staff sign-in: the public row stays on public."""

    def form_valid(self, form):
        user = form.get_user()
        login_staff(self.request, user)
        record_event(
            AuthEventType.LOGIN_SUCCESS,
            user=user,
            request=self.request,
        )
        return HttpResponseRedirect(self.get_success_url())


def staff_admin_login(request, extra_context=None):
    if request.method == "GET" and admin.site.has_permission(request):
        index_path = reverse("admin:index", current_app=admin.site.name)
        return HttpResponseRedirect(index_path)

    context = {
        **admin.site.each_context(request),
        "title": _("Log in"),
        "subtitle": None,
        "app_path": request.get_full_path(),
        "username": request.user.get_username(),
    }
    if (
        REDIRECT_FIELD_NAME not in request.GET
        and REDIRECT_FIELD_NAME not in request.POST
    ):
        context[REDIRECT_FIELD_NAME] = reverse(
            "admin:index",
            current_app=admin.site.name,
        )
    context.update(extra_context or {})
    request.current_app = admin.site.name
    return StaffAdminLoginView.as_view(
        extra_context=context,
        authentication_form=StaffAdminAuthenticationForm,
        template_name=admin.site.login_template or "admin/login.html",
    )(request)


admin.site.login_form = StaffAdminAuthenticationForm
admin.site.login = staff_admin_login
if settings.DJANGO_ADMIN_FORCE_ALLAUTH:
    # Force the admin sign-in process to go through the django-allauth workflow:
    # https://docs.allauth.org/en/latest/common/admin.html#admin
    admin.autodiscover()
    admin.site.login = secure_admin_login(admin.site.login)  # type: ignore[method-assign]
