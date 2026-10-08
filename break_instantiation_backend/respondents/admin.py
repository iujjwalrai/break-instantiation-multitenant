from django.contrib import admin

from .models import MagicLoginToken
from .models import Respondent
from .models import RespondentSession


@admin.register(Respondent)
class RespondentAdmin(admin.ModelAdmin):
    list_display = ["email", "disabled_at", "created"]
    search_fields = ["email"]
    ordering = ["email"]


@admin.register(MagicLoginToken)
class MagicLoginTokenAdmin(admin.ModelAdmin):
    list_display = ["respondent", "expires_at", "used", "used_at"]
    readonly_fields = ["token_hash", "expires_at", "used", "used_at"]


@admin.register(RespondentSession)
class RespondentSessionAdmin(admin.ModelAdmin):
    list_display = ["respondent", "expires_at", "last_used_at", "revoked_at"]
    readonly_fields = ["token_hash", "expires_at", "last_used_at", "revoked_at"]
