from django.contrib import admin

from .models import AssessmentResult


class ReadOnlyAdminMixin:
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(AssessmentResult)
class AssessmentResultAdmin(ReadOnlyAdminMixin, admin.ModelAdmin):
    list_display = ["client", "assessment", "http_status", "scored_at"]
    search_fields = ["client__email", "client__full_name"]
    readonly_fields = ["payload", "http_status", "scored_at", "created_at"]
