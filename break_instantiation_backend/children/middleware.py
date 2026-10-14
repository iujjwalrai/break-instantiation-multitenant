from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.db import connection
from django.http import Http404
from django_tenants.middleware.main import TenantMainMiddleware
from django_tenants.utils import get_public_schema_name

from break_instantiation_backend.children.models import ChildStatus
from break_instantiation_backend.users.roles import can_sign_in

# Client, audit, questionnaire, and result tables live in a child schema.
_TENANT_ADMIN_LABELS = ("clients", "audit", "questionnaires", "results")


def _tenant_admin_path(path: str) -> bool:
    admin_root = "/" + settings.ADMIN_URL.strip("/") + "/"
    return any(
        path.startswith(f"{admin_root}{label}/") for label in _TENANT_ADMIN_LABELS
    )


# The control store. Not a company, so it has no Child row and no domain.
class PublicControl:
    schema_name = "public"


class TenantHostMiddleware(TenantMainMiddleware):
    """`localhost` is the public admin. Any other host must be a child address."""

    def get_tenant(self, domain_model, hostname):
        if hostname in {"localhost", "127.0.0.1"}:
            return PublicControl()
        return super().get_tenant(domain_model, hostname)


# Anonymous staff sign-in has to work before a session exists. Everything
# else on a child that is not live is for a signed-in admin or backend admin.
_OPEN_PREFIXES = (
    "/api/staff/",
    "/api/look/",
    "/admin/",
    "/accounts/",
    "/static/",
    "/media/",
    "/__debug__/",
)


class ChildNotLiveMiddleware:
    """A draft host still answers that child's admins and a backend admin."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if connection.schema_name == get_public_schema_name():
            if _tenant_admin_path(request.path):
                raise PermissionDenied
            return self.get_response(request)
        tenant = getattr(request, "tenant", None)
        if tenant is None or getattr(tenant, "status", None) == ChildStatus.LIVE:
            return self.get_response(request)
        if request.path.startswith(_OPEN_PREFIXES):
            return self.get_response(request)
        if can_sign_in(getattr(request, "user", None)):
            return self.get_response(request)
        msg = "This company is not live."
        raise Http404(msg)
