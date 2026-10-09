from django.contrib import admin

from .models import Client
from .models import ClientPortalInvite
from .models import ClientSession
from .models import ClientUser
from .models import MagicLoginToken


@admin.register(Client)
class ClientAdmin(admin.ModelAdmin):
    list_display = ["full_name", "email", "admin", "client_user", "created"]
    search_fields = ["full_name", "email"]
    raw_id_fields = ["admin", "client_user"]


@admin.register(ClientUser)
class ClientUserAdmin(admin.ModelAdmin):
    list_display = ["email", "disabled_at", "created"]
    search_fields = ["email"]


@admin.register(ClientPortalInvite)
class ClientPortalInviteAdmin(admin.ModelAdmin):
    list_display = ["invited_email", "target_client", "expires_at", "used", "used_at"]
    readonly_fields = ["token_hash", "expires_at", "used", "used_at", "opened_at"]


@admin.register(MagicLoginToken)
class MagicLoginTokenAdmin(admin.ModelAdmin):
    list_display = ["client_user", "expires_at", "used", "used_at"]
    readonly_fields = ["token_hash", "expires_at", "used", "used_at"]


@admin.register(ClientSession)
class ClientSessionAdmin(admin.ModelAdmin):
    list_display = ["client_user", "expires_at", "last_used_at", "revoked_at"]
    readonly_fields = ["token_hash", "expires_at", "last_used_at", "revoked_at"]
