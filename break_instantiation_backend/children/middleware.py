import re
import sys
from types import ModuleType

from django.conf import settings
from django.core.exceptions import DisallowedHost
from django.core.exceptions import PermissionDenied
from django.db import connection
from django.http import Http404
from django.http import HttpResponseNotFound
from django.urls import URLResolver
from django.urls import set_urlconf
from django.utils.module_loading import import_string
from django_tenants.middleware.main import TenantMainMiddleware
from django_tenants.utils import get_public_schema_name
from django_tenants.utils import get_subfolder_prefix
from django_tenants.utils import get_tenant_domain_model

from break_instantiation_backend.children.models import ChildStatus
from break_instantiation_backend.users.roles import can_sign_in

# Client, audit, questionnaire, and result tables live in a child schema.
_TENANT_ADMIN_LABELS = ("clients", "audit", "questionnaires", "results")

# A path slug is a ChildDomain row too, next to host rows like ej.localhost.
# No dots, so a slug can never match a host row.
SLUG_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]*$")


def _tenant_admin_path(path: str) -> bool:
    admin_root = "/" + settings.ADMIN_URL.strip("/") + "/"
    return any(
        path.startswith(f"{admin_root}{label}/") for label in _TENANT_ADMIN_LABELS
    )


def tenant_relative_path(request) -> str:
    """`request.path` without the /t/<slug> prefix, for fixed-path checks."""
    subfolder = getattr(getattr(request, "tenant", None), "domain_subfolder", None)
    if not subfolder:
        return request.path
    return request.path[len(f"/{get_subfolder_prefix()}/{subfolder}") :]


# The control store. Not a company, so it has no Child row and no domain.
class PublicControl:
    schema_name = "public"


class _FixedPrefixPattern:
    """Matches `t/<slug>/` as written, for one company's URLConf.

    django-tenants' own prefix pattern looks the company up on the thread's
    DB connection at every match. Under ASGI the URL is resolved on another
    thread than the middleware's, which has no company, so that fails.
    """

    converters = {}

    def __init__(self, prefix: str):
        self.prefix = prefix
        self.regex = re.compile(prefix)

    def match(self, path):
        if path.startswith(self.prefix):
            return path[len(self.prefix) :], (), {}
        return None

    def check(self):
        return []

    def describe(self):
        return f"'{self.prefix}'"

    def __str__(self):
        return self.prefix


class _CompanyURLConf(ModuleType):
    """ROOT_URLCONF behind one company's prefix. reverse() then adds it."""

    def __init__(self, name: str, prefix: str):
        super().__init__(name)
        self._prefix = prefix

    def __getattr__(self, attr):
        try:
            value = import_string(f"{settings.ROOT_URLCONF}.{attr}")
        except ImportError as exc:
            raise AttributeError(attr) from exc
        if attr == "urlpatterns":
            return [URLResolver(_FixedPrefixPattern(self._prefix), list(value))]
        return value


def company_urlconf(slug: str) -> str:
    """The URLConf module for /t/<slug>/, made once per company."""
    name = f"{settings.ROOT_URLCONF}_company_{slug}"
    if name not in sys.modules:
        sys.modules[name] = _CompanyURLConf(name, f"{get_subfolder_prefix()}/{slug}/")
    return name


class TenantHostMiddleware(TenantMainMiddleware):
    """/t/<slug>/ selects a company. Otherwise the host decides.

    On a public host (localhost, the Render host) the root is the control
    store, so /admin/ there is the public admin. A company host such as
    ej.localhost still selects that company at the root. Any other host is
    a 404.
    """

    def process_request(self, request):
        connection.set_schema_to_public()
        try:
            hostname = self.hostname_from_request(request)
        except DisallowedHost:
            return HttpResponseNotFound()
        domain_model = get_tenant_domain_model()

        prefix = f"/{get_subfolder_prefix()}/"
        if request.path.startswith(prefix):
            slug = request.path[len(prefix) :].split("/", 1)[0]
            if not SLUG_PATTERN.match(slug):
                msg = "No company for that path."
                raise Http404(msg)
            try:
                tenant = self.get_tenant(domain_model, slug)
            except domain_model.DoesNotExist:
                msg = f'No company for path "{slug}".'
                raise Http404(msg) from None
            tenant.domain_subfolder = slug
            request.urlconf = company_urlconf(slug)
            set_urlconf(request.urlconf)
        elif hostname in settings.TENANT_PUBLIC_HOSTS:
            tenant = PublicControl()
        else:
            try:
                tenant = self.get_tenant(domain_model, hostname)
            except domain_model.DoesNotExist:
                msg = f'No company for host "{hostname}".'
                raise Http404(msg) from None
        tenant.domain_url = hostname
        request.tenant = tenant
        connection.set_tenant(tenant)
        return None

    def process_response(self, request, response):
        """Keep each company's cookies to its own /t/<slug>/ path.

        Without this, signing in to two companies' Django admin in one
        browser on one API host would share one session cookie.
        """
        subfolder = getattr(getattr(request, "tenant", None), "domain_subfolder", None)
        if subfolder:
            path = f"/{get_subfolder_prefix()}/{subfolder}/"
            names = (
                settings.SESSION_COOKIE_NAME,
                settings.CSRF_COOKIE_NAME,
                settings.CLIENT_SESSION_COOKIE_NAME,
            )
            for name in names:
                if name in response.cookies:
                    response.cookies[name]["path"] = path
        return response


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
    """A draft company still answers its admins and a backend admin."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        path = tenant_relative_path(request)
        if connection.schema_name == get_public_schema_name():
            if _tenant_admin_path(path):
                raise PermissionDenied
            return self.get_response(request)
        tenant = getattr(request, "tenant", None)
        if tenant is None or getattr(tenant, "status", None) == ChildStatus.LIVE:
            return self.get_response(request)
        if path.startswith(_OPEN_PREFIXES):
            return self.get_response(request)
        if can_sign_in(getattr(request, "user", None)):
            return self.get_response(request)
        msg = "This company is not live."
        raise Http404(msg)
