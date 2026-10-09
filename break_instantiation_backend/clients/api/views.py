from django.db.models import Prefetch
from rest_framework import status
from rest_framework.authentication import SessionAuthentication
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.mixins import CreateModelMixin
from rest_framework.mixins import ListModelMixin
from rest_framework.mixins import RetrieveModelMixin
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet

from break_instantiation_backend.clients.models import Client
from break_instantiation_backend.clients.models import ClientPortalInvite
from break_instantiation_backend.clients.origin import caller_origin
from break_instantiation_backend.clients.services import issue_portal_invite
from break_instantiation_backend.clients.tasks import send_portal_invite_email
from break_instantiation_backend.users.api.permissions import IsStaffMember
from break_instantiation_backend.users.models import User
from break_instantiation_backend.users.roles import is_super_admin

from .serializers import ClientCreateSerializer
from .serializers import ClientSerializer


class ClientViewSet(
    ListModelMixin,
    CreateModelMixin,
    RetrieveModelMixin,
    GenericViewSet,
):
    """Profiles an admin creates, then invites.

    An admin sees only clients they are responsible for. A super admin
    sees every client. A client outside that set is a 404.
    """

    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated, IsStaffMember]
    queryset = Client.objects.all()
    serializer_class = ClientSerializer

    def get_queryset(self):
        queryset = Client.objects.select_related(
            "admin",
            "client_user",
        ).prefetch_related(
            Prefetch(
                "portal_invites",
                queryset=ClientPortalInvite.objects.order_by("-created"),
            ),
        )
        user = self.request.user
        if not is_super_admin(user):
            queryset = queryset.filter(admin=user)
        return queryset.order_by("-created")

    def get_serializer_class(self):
        if self.action == "create":
            return ClientCreateSerializer
        return ClientSerializer

    def create(self, request, *args, **kwargs):
        write = ClientCreateSerializer(
            data=request.data,
            context={"request": request},
        )
        write.is_valid(raise_exception=True)
        client = write.save()
        return Response(
            ClientSerializer(client).data,
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=["post"])
    def invite(self, request, pk=None):
        """Email a link. Redeeming it creates the `ClientUser`."""
        client = self.get_object()
        if client.client_user_id is not None:
            raise ValidationError(
                {"detail": "This client already has portal access."},
            )
        origin = caller_origin(request)
        if origin is None:
            raise ValidationError({"detail": "Origin header is required."})
        assert isinstance(request.user, User)
        _invite, raw_token = issue_portal_invite(
            target_client=client,
            invited_by=request.user,
        )
        send_portal_invite_email.delay(client.email, raw_token, origin)
        return Response(
            {"detail": "Invitation sent."},
            status=status.HTTP_202_ACCEPTED,
        )
