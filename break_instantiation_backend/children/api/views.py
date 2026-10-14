from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from break_instantiation_backend.children.look import on_public_schema
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
