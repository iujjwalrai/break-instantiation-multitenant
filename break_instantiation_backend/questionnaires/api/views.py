from __future__ import annotations

import typing

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from break_instantiation_backend.clients.authentication import (
    ClientSessionAuthentication,
)
from break_instantiation_backend.clients.models import ClientUser
from break_instantiation_backend.questionnaires.models import Assessment
from break_instantiation_backend.questionnaires.models import ConsentRecord
from break_instantiation_backend.questionnaires.models import ConsentTemplate
from break_instantiation_backend.questionnaires.routing import RoutingError
from break_instantiation_backend.questionnaires.services import AssessmentCompleteError
from break_instantiation_backend.questionnaires.services import ConsentRequiredError
from break_instantiation_backend.questionnaires.services import QuestionMismatchError
from break_instantiation_backend.questionnaires.services import (
    QuestionnaireNotConfiguredError,
)
from break_instantiation_backend.questionnaires.services import SessionState
from break_instantiation_backend.questionnaires.services import grant_consent
from break_instantiation_backend.questionnaires.services import start_assessment
from break_instantiation_backend.questionnaires.services import submit_answers

from .serializers import AnswerInSerializer
from .serializers import ConsentRecordOutSerializer
from .serializers import ConsentTemplateOutSerializer
from .serializers import QuestionOutSerializer

if typing.TYPE_CHECKING:
    from rest_framework.request import Request


def serialize_state(assessment_status: str, state: SessionState) -> dict:
    return {
        "assessment_status": assessment_status,
        "completed": state.completed,
        "progress": {"answered": state.answered_count, "total": state.total_count},
        "is_new_section": state.is_new_section,
        # One element for every ordinary section; only longer where the
        # graph has a run of questions with nothing to decide between them
        # -- see `routing.unconditional_run`.
        "questions": QuestionOutSerializer(state.next_questions, many=True).data,
    }


class ConsentTemplateView(APIView):
    """The one active consent wording. A client reads this, then grants it."""

    authentication_classes = [ClientSessionAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        template = ConsentTemplate.objects.filter(is_active=True).first()
        if template is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        return Response(ConsentTemplateOutSerializer(template).data)


class ConsentGrantView(APIView):
    authentication_classes = [ClientSessionAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        """The client's own consent record, if they've granted it and it's
        still in effect -- `404` if they never granted it, or a staff
        member withdrew it on their behalf (functionally the same as
        never having granted it: they need to consent again, via `POST`
        below, before they can start/resume the questionnaire).
        `ConsentRecord` is `UNIQUE(client)`, so this is always at most one
        row, not a history/list.
        """
        assert isinstance(request.user, ClientUser)
        try:
            record = request.user.client.consent_record
        except ConsentRecord.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)
        if record.withdrawn_at is not None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        return Response(
            ConsentRecordOutSerializer(
                ConsentRecord.objects.select_related("template").get(pk=record.pk),
            ).data,
        )

    def post(self, request: Request) -> Response:
        assert isinstance(request.user, ClientUser)
        record = grant_consent(client=request.user.client)
        record = ConsentRecord.objects.select_related("template").get(pk=record.pk)
        return Response(ConsentRecordOutSerializer(record).data)


class AssessmentStartView(APIView):
    authentication_classes = [ClientSessionAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request: Request) -> Response:
        assert isinstance(request.user, ClientUser)
        try:
            assessment, _session, state = start_assessment(client=request.user.client)
        except ConsentRequiredError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_403_FORBIDDEN)
        except QuestionnaireNotConfiguredError as exc:
            return Response(
                {"detail": str(exc)},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        return Response(serialize_state(assessment.status, state))


class AssessmentAnswerBatchView(APIView):
    """Submit several answers from one screen (see `SessionState.next_questions`)
    in a single request, all-or-nothing.
    """

    authentication_classes = [ClientSessionAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request: Request) -> Response:
        assert isinstance(request.user, ClientUser)
        serializer = AnswerInSerializer(
            data=request.data.get("answers", []),
            many=True,
            allow_empty=False,
        )
        serializer.is_valid(raise_exception=True)

        try:
            assessment = request.user.client.assessment
        except Assessment.DoesNotExist:
            return Response(
                {"detail": "The questionnaire has not been started."},
                status=status.HTTP_409_CONFLICT,
            )

        try:
            state = submit_answers(
                session=assessment.session,
                answers=[
                    (item["question"], item) for item in serializer.validated_data
                ],
            )
        except QuestionMismatchError as exc:
            # A racing request may have advanced it since `assessment` was read.
            assessment.session.refresh_from_db(fields=["current_question"])
            return Response(
                {
                    "detail": str(exc),
                    "current_question_id": assessment.session.current_question_id,
                },
                status=status.HTTP_409_CONFLICT,
            )
        except AssessmentCompleteError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)
        except RoutingError as exc:
            return Response(
                {"detail": str(exc)},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        assessment.refresh_from_db(fields=["status"])
        return Response(serialize_state(assessment.status, state))
