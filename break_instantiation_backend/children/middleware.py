import hmac

from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.db import connection
from django.http import Http404
from django_tenants.middleware.main import TenantMainMiddleware
from django_tenants.utils import get_public_schema_name
from django_tenants.utils import remove_www

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


_PUBLIC_HOSTS = {"localhost", "127.0.0.1"}
COMPANY_HOST_HEADER = "HTTP_X_COMPANY_HOST"
COMPANY_KEY_HEADER = "HTTP_X_COMPANY_KEY"


def _company_host(request) -> str | None:
    """The company address a trusted frontend named, or None for the host.

    One API host can then serve every company: each frontend sends its own
    address, which is stored as one of that company's domains. The header
    counts only with the shared key, and it can never select public.
    """
    named = request.META.get(COMPANY_HOST_HEADER, "")
    secret = settings.COMPANY_HOST_SECRET
    if not named or not secret:
        return None
    key = request.META.get(COMPANY_KEY_HEADER, "")
    if not hmac.compare_digest(key.encode(), secret.encode()):
        msg = "Unknown frontend."
        raise PermissionDenied(msg)
    hostname = remove_www(named.strip().lower().split(":")[0])
    if not hostname or hostname in _PUBLIC_HOSTS:
        msg = "No company for that address."
        raise Http404(msg)
    return hostname


class TenantHostMiddleware(TenantMainMiddleware):
    """`localhost` is the public admin. Any other host must be a child address.

    A frontend server may name the company in X-Company-Host instead.
    """

    def hostname_from_request(self, request):
        return _company_host(request) or super().hostname_from_request(request)

    def get_tenant(self, domain_model, hostname):
        if hostname in _PUBLIC_HOSTS:
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
