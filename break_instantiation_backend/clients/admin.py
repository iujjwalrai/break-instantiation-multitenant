from django import forms
from django.contrib import admin
from django.contrib import messages

from break_instantiation_backend.audit.models import ClientActivityEventType
from break_instantiation_backend.audit.services import record_client_event
from break_instantiation_backend.children.schema import enqueue_child_task

from .models import Client
from .models import ClientPortalInvite
from .models import ClientSession
from .models import ClientUser
from .models import MagicLoginToken
from .services import disable_client_user
from .services import issue_portal_invite
from .services import reenable_client_user
from .tasks import send_portal_invite_email


class ClientAdminForm(forms.ModelForm):
    class Meta:
        model = Client
        fields = ["full_name", "email", "client_user"]

    def clean_email(self):
        email = self.cleaned_data["email"]
        existing = Client.objects.filter(email__iexact=email)
        if self.instance.pk:
            existing = existing.exclude(pk=self.instance.pk)
        if existing.exists():
            msg = "A client with this email already exists."
            raise forms.ValidationError(msg)
        return email


@admin.register(Client)
class ClientAdmin(admin.ModelAdmin):
    """Create and edit a client's name and email.

    Delete stays off. Portal invites and append-only activity rows use
    ``PROTECT``, and creating a client records an activity row, so a
    delete would fail for any client that has been saved through here
    or invited.
    """

    form = ClientAdminForm
    list_display = ["full_name", "email", "client_user", "created"]
    search_fields = ["full_name", "email"]
    readonly_fields = ["client_user"]
    fields = ["full_name", "email", "client_user"]
    ordering = ["full_name"]

    def has_delete_permission(self, request, obj=None):
        return False

    def save_model(self, request, obj, form, change):
        previous = Client.objects.get(pk=obj.pk) if change else None
        super().save_model(request, obj, form, change)
        if not getattr(request.user, "is_authenticated", False):
            return
        if previous is None:
            record_client_event(
                ClientActivityEventType.CLIENT_CREATED,
                actor=request.user,
                client=obj,
            )
            return
        changes = {}
        if previous.full_name != obj.full_name:
            changes["full_name"] = {
                "old": previous.full_name,
                "new": obj.full_name,
            }
        if previous.email != obj.email:
            changes["email"] = {"old": previous.email, "new": obj.email}
        if changes:
            record_client_event(
                ClientActivityEventType.CLIENT_UPDATED,
                actor=request.user,
                client=obj,
                changes=changes,
            )


@admin.register(ClientUser)
class ClientUserAdmin(admin.ModelAdmin):
    """Portal logins. Enable and disable are the only edits.

    The login row is created when an invite is redeemed. ``disabled_at``
    is set by the actions below. There is no portal-access event type on
    the activity log; disabling revokes sessions, which records logout.
    """

    list_display = ["email", "disabled_at", "created"]
    search_fields = ["email"]
    ordering = ["email"]
    readonly_fields = ["email", "disabled_at", "created", "modified"]
    actions = ["disable_portal_access", "reenable_portal_access"]

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.action(description="Disable client portal access")
    def disable_portal_access(self, request, queryset):
        disabled = 0
        for client_user in queryset.filter(disabled_at__isnull=True):
            disable_client_user(client_user, request=request)
            disabled += 1
        skipped = queryset.count() - disabled
        self.message_user(request, f"Disabled {disabled} client user(s).")
        if skipped:
            self.message_user(
                request,
                f"Skipped {skipped} client user(s) already disabled.",
                level=messages.WARNING,
            )

    @admin.action(description="Re-enable client portal access")
    def reenable_portal_access(self, request, queryset):
        reenabled = 0
        for client_user in queryset.filter(disabled_at__isnull=False):
            reenable_client_user(client_user)
            reenabled += 1
        skipped = queryset.count() - reenabled
        self.message_user(request, f"Re-enabled {reenabled} client user(s).")
        if skipped:
            self.message_user(
                request,
                f"Skipped {skipped} client user(s) already active.",
                level=messages.WARNING,
            )


class ClientPortalInviteAddForm(forms.ModelForm):
    """Pick a client who has no login. The service stores the token hash."""

    class Meta:
        model = ClientPortalInvite
        fields = ["target_client"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["target_client"].queryset = Client.objects.filter(
            client_user__isnull=True,
        )

    def clean_target_client(self):
        client = self.cleaned_data["target_client"]
        if client.client_user_id is not None:
            msg = "This client already has portal access."
            raise forms.ValidationError(msg)
        return client


@admin.register(ClientPortalInvite)
class ClientPortalInviteAdmin(admin.ModelAdmin):
    """Issue an invite through ``issue_portal_invite``. Rows are not edited."""

    list_display = [
        "invited_email",
        "target_client",
        "invited_by",
        "status",
        "expires_at",
        "used",
        "used_at",
    ]
    search_fields = ["invited_email", "target_client__email", "invited_by__email"]
    autocomplete_fields = ["target_client"]
    ordering = ["-created"]

    def get_form(self, request, obj=None, **kwargs):
        if obj is None:
            kwargs["form"] = ClientPortalInviteAddForm
        return super().get_form(request, obj, **kwargs)

    def get_fields(self, request, obj=None):
        if obj is None:
            return ["target_client"]
        return [
            "invited_email",
            "target_client",
            "invited_by",
            "expires_at",
            "opened_at",
            "used",
            "used_at",
            "created",
        ]

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def save_model(self, request, obj, form, change):
        if change:
            return
        invite, raw_token = issue_portal_invite(
            target_client=form.cleaned_data["target_client"],
            invited_by=request.user,
            request=request,
        )
        enqueue_child_task(send_portal_invite_email, invite.invited_email, raw_token)
        obj.pk = invite.pk
        obj.refresh_from_db()


class IssuedTokenAdmin(admin.ModelAdmin):
    """Created by the login services. The raw token is never stored."""

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(MagicLoginToken)
class MagicLoginTokenAdmin(IssuedTokenAdmin):
    list_display = ["client_user", "expires_at", "used", "used_at", "created"]
    search_fields = ["client_user__email"]
    fields = ["client_user", "expires_at", "used", "used_at", "created"]


@admin.register(ClientSession)
class ClientSessionAdmin(IssuedTokenAdmin):
    list_display = [
        "client_user",
        "expires_at",
        "last_used_at",
        "revoked_at",
        "created",
    ]
    search_fields = ["client_user__email"]
    fields = ["client_user", "expires_at", "last_used_at", "revoked_at", "created"]
