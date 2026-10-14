from django.db.models import Prefetch
from rest_framework import status
from rest_framework.authentication import SessionAuthentication
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.mixins import CreateModelMixin
from rest_framework.mixins import ListModelMixin
from rest_framework.mixins import RetrieveModelMixin
from rest_framework.mixins import UpdateModelMixin
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet

from break_instantiation_backend.audit.models import ClientActivityEventType
from break_instantiation_backend.audit.services import record_client_event
from break_instantiation_backend.children.schema import enqueue_child_task
from break_instantiation_backend.clients.models import Client
from break_instantiation_backend.clients.models import ClientPortalInvite
from break_instantiation_backend.clients.services import issue_portal_invite
from break_instantiation_backend.clients.tasks import send_portal_invite_email
from break_instantiation_backend.questionnaires.services import ConsentRequiredError
from break_instantiation_backend.questionnaires.services import (
    reinstate_consent as reinstate_client_consent,
)
from break_instantiation_backend.questionnaires.services import (
    withdraw_consent as withdraw_client_consent,
)
from break_instantiation_backend.users.api.permissions import IsTenantStaff
from break_instantiation_backend.users.models import User
from break_instantiation_backend.users.staff_auth import CrossSchemaInviteError

from .serializers import ClientCreateSerializer
from .serializers import ClientSerializer
from .serializers import ClientUpdateSerializer


def _record_client_changes(*, actor: User, client: Client, before: dict) -> None:
    """Record a profile edit when name or email actually change."""
    after = {"full_name": client.full_name, "email": client.email}
    changes = {
        field: {"old": before[field], "new": value}
        for field, value in after.items()
        if before[field] != value
    }
    if changes:
        record_client_event(
            ClientActivityEventType.CLIENT_UPDATED,
            actor=actor,
            client=client,
            changes=changes,
        )


class ClientViewSet(
    ListModelMixin,
    CreateModelMixin,
    RetrieveModelMixin,
    UpdateModelMixin,
    GenericViewSet,
):
    """Profiles an admin creates, then invites.

    A customer admin and a backend admin see every client in this child.
    """

    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated, IsTenantStaff]
    queryset = Client.objects.all()
    serializer_class = ClientSerializer

    def get_queryset(self):
        return (
            Client.objects.select_related("client_user", "consent_record")
            .prefetch_related(
                Prefetch(
                    "portal_invites",
                    queryset=ClientPortalInvite.objects.order_by("-created"),
                ),
            )
            .order_by("-created")
        )

    def get_serializer_class(self):
        if self.action == "create":
            return ClientCreateSerializer
        if self.action in {"update", "partial_update"}:
            return ClientUpdateSerializer
        return ClientSerializer

    def create(self, request, *args, **kwargs):
        write = ClientCreateSerializer(
            data=request.data,
            context={"request": request},
        )
        write.is_valid(raise_exception=True)
        client = write.save()
        assert isinstance(request.user, User)
        record_client_event(
            ClientActivityEventType.CLIENT_CREATED,
            actor=request.user,
            client=client,
        )
        return Response(
            ClientSerializer(client).data,
            status=status.HTTP_201_CREATED,
        )

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop("partial", False)
        instance = self.get_object()
        before = {
            "full_name": instance.full_name,
            "email": instance.email,
        }
        write = ClientUpdateSerializer(
            instance,
            data=request.data,
            partial=partial,
            context={"request": request},
        )
        write.is_valid(raise_exception=True)
        client = write.save()
        assert isinstance(request.user, User)
        _record_client_changes(actor=request.user, client=client, before=before)
        return Response(ClientSerializer(client).data)

    @action(detail=True, methods=["post"])
    def invite(self, request, pk=None):
        """Email a link. Redeeming it creates the `ClientUser`."""
        client = self.get_object()
        if client.client_user_id is not None:
            raise ValidationError(
                {"detail": "This client already has portal access."},
            )
        assert isinstance(request.user, User)
        try:
            _invite, raw_token = issue_portal_invite(
                target_client=client,
                invited_by=request.user,
                request=request,
            )
        except CrossSchemaInviteError as exc:
            raise ValidationError({"detail": str(exc)}) from exc
        enqueue_child_task(send_portal_invite_email, client.email, raw_token)
        return Response(
            {"detail": "Invitation sent."},
            status=status.HTTP_202_ACCEPTED,
        )

    @action(detail=True, methods=["post"], url_path="withdraw-consent")
    def withdraw_consent(self, request, pk=None):
        """Withdraw this client's questionnaire consent. Staff only."""
        client = self.get_object()
        assert isinstance(request.user, User)
        try:
            withdraw_client_consent(client=client, actor=request.user)
        except ConsentRequiredError as exc:
            raise ValidationError({"detail": str(exc)}) from exc
        # The queryset select_related the consent row before this write.
        client = self.get_queryset().get(pk=client.pk)
        return Response(ClientSerializer(client).data)

    @action(detail=True, methods=["post"], url_path="reinstate-consent")
    def reinstate_consent(self, request, pk=None):
        """Restore a withdrawn consent. Staff only."""
        client = self.get_object()
        assert isinstance(request.user, User)
        try:
            reinstate_client_consent(client=client, actor=request.user)
        except ConsentRequiredError as exc:
            raise ValidationError({"detail": str(exc)}) from exc
        client = self.get_queryset().get(pk=client.pk)
        return Response(ClientSerializer(client).data)
