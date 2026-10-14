from django_tenants.utils import get_public_schema_name
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from break_instantiation_backend.children.look import on_public_schema
from break_instantiation_backend.children.look import public_look
from break_instantiation_backend.children.models import Child
from break_instantiation_backend.children.models import ChildStatus
from break_instantiation_backend.children.schema import current_look


class LookView(APIView):
    """Name, logo, and colors for the company this host already selected.

    The login page reads this before anyone signs in. `localhost` is the
    control store and has no company look.
    """

    authentication_classes = []
    permission_classes = [AllowAny]

    def get(self, request):
        if on_public_schema():
            return Response({"detail": "No company for this host."}, status=404)
        return Response(current_look())


class CompanyListView(APIView):
    """Live companies and their path slugs, for the admin landing page.

    Public control store only. A draft company, or one with no path slug,
    is left out. This lists every customer to anyone who asks.
    """

    authentication_classes = []
    permission_classes = [AllowAny]

    def get(self, request):
        if not on_public_schema():
            return Response({"detail": "Not found."}, status=404)
        children = (
            Child.objects.filter(status=ChildStatus.LIVE)
            .exclude(schema_name=get_public_schema_name())
            .prefetch_related("domains")
            .order_by("name")
        )
        rows = []
        for child in children:
            slug = next(
                (d.domain for d in child.domains.all() if "." not in d.domain),
                "",
            )
            if slug:
                look = public_look(name=child.name, look=child.look)
                rows.append(
                    {"slug": slug, "name": look["name"], "colors": look["colors"]},
                )
        return Response(rows)
