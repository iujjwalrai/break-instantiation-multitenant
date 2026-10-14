from django.contrib import admin
from django.db import connection
from django.db.utils import ProgrammingError
from django.utils.html import format_html
from django.utils.html import format_html_join
from django_tenants.utils import get_public_schema_name
from django_tenants.utils import schema_context

from break_instantiation_backend.clients.models import Client
from break_instantiation_backend.users.models import User

from .look import public_look
from .models import Child
from .models import ChildDomain

# These tables exist in a child schema, not on public. The public admin
# lists companies and reads into each schema instead of opening empty apps.
_TENANT_APP_LABELS = {"clients", "audit", "questionnaires", "results"}


def _person(email: str, name: str, role: str) -> str:
    bits = [email]
    if name:
        bits.append(name)
    if role:
        bits.append(role)
    return ", ".join(bits)


def _on_public() -> bool:
    return connection.schema_name == get_public_schema_name()


class PublicOnlyAdmin(admin.ModelAdmin):
    """Child rows are the control store. A child schema does not edit them."""

    def has_module_permission(self, request):
        return _on_public() and super().has_module_permission(request)

    def has_view_permission(self, request, obj=None):
        return _on_public() and super().has_view_permission(request, obj)

    def has_add_permission(self, request):
        return _on_public() and super().has_add_permission(request)

    def has_change_permission(self, request, obj=None):
        return _on_public() and super().has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        return _on_public() and super().has_delete_permission(request, obj)


def hide_tenant_models_on_public() -> None:
    """Called after admin autodiscover. The public index lists companies only."""
    current = admin.site.get_app_list
    if getattr(current, "hides_tenant_apps", False):
        return

    def get_app_list(request, app_label=None):
        apps = current(request, app_label)
        if not _on_public():
            return apps
        return [app for app in apps if app["app_label"] not in _TENANT_APP_LABELS]

    get_app_list.hides_tenant_apps = True
    admin.site.get_app_list = get_app_list


def _people_list(rows: list[str], empty: str):
    rendered = format_html_join("", "<li>{}</li>", ((row,) for row in rows))
    if not rendered:
        return format_html("<li>{}</li>", empty)
    return rendered


@admin.register(Child)
class ChildAdmin(PublicOnlyAdmin):
    list_display = ["name", "schema_name", "status", "look_summary", "client_site_url"]
    list_filter = ["status"]
    search_fields = ["name", "schema_name"]
    ordering = ["name"]
    readonly_fields = ["company_roster", "company_admin_link"]
    fieldsets = (
        (
            None,
            {
                "fields": (
                    "name",
                    "schema_name",
                    "status",
                    "look",
                    "report_style",
                    "scoring_route",
                    "client_site_url",
                    "company_admin_link",
                ),
            },
        ),
        ("In this company", {"fields": ("company_roster",)}),
    )

    def changeform_view(self, request, object_id=None, form_url="", extra_context=None):
        self._request = request
        try:
            return super().changeform_view(
                request,
                object_id,
                form_url,
                extra_context,
            )
        finally:
            self._request = None

    @admin.display(description="Look")
    def look_summary(self, obj: Child):
        look = public_look(name=obj.name, look=obj.look)
        color = look["colors"]["primary"]
        return format_html(
            '<span style="display:inline-block;width:0.75em;height:0.75em;'
            "background:{};border:1px solid #ccc;vertical-align:middle;"
            'margin-right:0.4em"></span>{}',
            color,
            look["name"],
        )

    @admin.display(description="Company admin")
    def company_admin_link(self, obj: Child | None):
        if obj is None or not obj.pk:
            return "Save the company, then this links to its tables."
        domain = obj.domains.filter(is_primary=True).first() or obj.domains.first()
        if domain is None:
            return "This company has no address yet."
        request = getattr(self, "_request", None)
        host = domain.domain
        if request is not None and request.get_port() not in {"80", "443"}:
            host = f"{host}:{request.get_port()}"
        scheme = "https" if request is not None and request.is_secure() else "http"
        url = f"{scheme}://{host}/admin/"
        return format_html('<a href="{}">{}</a>', url, url)

    @admin.display(description="Admins and clients")
    def company_roster(self, obj: Child | None):
        if obj is None or not obj.pk or obj.schema_name in {"", "public"}:
            return "Save the company, then this lists the people stored in it."
        try:
            with schema_context(obj.schema_name):
                admins = [
                    _person(email, name, role)
                    for email, name, role in User.objects.order_by("email").values_list(
                        "email",
                        "name",
                        "role",
                    )
                ]
                clients = [
                    _person(email, full_name, "")
                    for full_name, email in Client.objects.order_by(
                        "email",
                    ).values_list("full_name", "email")
                ]
        except ProgrammingError:
            return "This company's storage is not ready."
        return format_html(
            "<p><strong>Admins</strong></p><ul>{}</ul>"
            "<p><strong>Clients</strong></p><ul>{}</ul>",
            _people_list(admins, "No admins yet."),
            _people_list(clients, "No clients yet."),
        )


@admin.register(ChildDomain)
class ChildDomainAdmin(PublicOnlyAdmin):
    list_display = ["domain", "tenant", "is_primary"]
    search_fields = ["domain"]
    ordering = ["domain"]
