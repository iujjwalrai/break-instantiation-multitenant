from django.contrib import admin

from .models import AdminActivityEvent
from .models import AssessmentActivityEvent
from .models import AuthEvent
from .models import ClientActivityEvent


class AppendOnlyAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(AuthEvent)
class AuthEventAdmin(AppendOnlyAdmin):
    list_display = ["event_type", "user", "client_user", "ip_address", "occurred_at"]
    list_filter = ["event_type"]
    date_hierarchy = "occurred_at"
    search_fields = ["user__email", "client_user__email"]


@admin.register(AdminActivityEvent)
class AdminActivityEventAdmin(AppendOnlyAdmin):
    list_display = [
        "event_type",
        "actor_user",
        "target_user",
        "previous_role_name",
        "new_role_name",
        "occurred_at",
    ]
    list_filter = ["event_type"]
    date_hierarchy = "occurred_at"
    search_fields = ["actor_user__email", "target_user__email"]


@admin.register(ClientActivityEvent)
class ClientActivityEventAdmin(AppendOnlyAdmin):
    list_display = ["event_type", "client", "actor_user", "occurred_at"]
    list_filter = ["event_type"]
    date_hierarchy = "occurred_at"
    search_fields = ["client__email", "client__full_name", "actor_user__email"]


@admin.register(AssessmentActivityEvent)
class AssessmentActivityEventAdmin(AppendOnlyAdmin):
    list_display = ["event_type", "client", "occurred_at"]
    list_filter = ["event_type"]
    date_hierarchy = "occurred_at"
    search_fields = ["client__email", "client__full_name"]
