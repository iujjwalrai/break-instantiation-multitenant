from __future__ import annotations

import typing
from dataclasses import dataclass

from django.db import IntegrityError
from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from break_instantiation_backend.audit.models import AssessmentActivityEventType
from break_instantiation_backend.audit.models import ClientActivityEventType
from break_instantiation_backend.audit.services import record_assessment_event
from break_instantiation_backend.audit.services import record_client_event
from break_instantiation_backend.children.schema import enqueue_child_task
from break_instantiation_backend.results.tasks import score_assessment_task

from . import routing
from .models import Answer
from .models import AnswerTypeChoices
from .models import Assessment
from .models import AssessmentStatus
from .models import ConsentRecord
from .models import ConsentTemplate
from .models import Question
from .models import QuestionnaireSession
from .models import QuestionnaireVersion
from .models import RoutingModel

if typing.TYPE_CHECKING:
    from uuid import UUID

    from break_instantiation_backend.clients.models import Client
    from break_instantiation_backend.users.models import User

# Re-exported so presentation stays defined in one place (`routing`).
BATCH_PRESENTATION_SECTION_CODES = routing.BATCH_PRESENTATION_SECTION_CODES


def grant_consent(*, client: Client) -> ConsentRecord:
    """Record the client's questionnaire consent, idempotently.

    A second call while consent is still in effect returns the existing
    row and does not write another audit event. A client who previously
    withdrew, then grants again, clears `withdrawn_at` and stamps whichever
    template is active now. That re-grant is the client's own act, so it
    is an assessment event (`CONSENT_GRANTED`), not a staff reinstate.
    """
    template = ConsentTemplate.objects.filter(is_active=True).first()
    record, created = ConsentRecord.objects.get_or_create(
        client=client,
        defaults={"template": template},
    )
    if created or record.withdrawn_at is not None:
        if not created:
            record.withdrawn_at = None
            record.template = template
            record.save(update_fields=["withdrawn_at", "template"])
        record_assessment_event(
            AssessmentActivityEventType.CONSENT_GRANTED,
            client=client,
        )
    return record


def withdraw_consent(*, client: Client, actor: User) -> ConsentRecord:
    """Withdraw questionnaire consent on the client's behalf.

    Staff-triggered. Already-withdrawn is a no-op. A client who never
    granted consent raises `ConsentRequiredError`. The audit row is a
    client activity event because a staff user is the actor.
    """
    try:
        record = ConsentRecord.objects.get(client=client)
    except ConsentRecord.DoesNotExist:
        msg = "This client has never granted questionnaire consent."
        raise ConsentRequiredError(msg) from None
    if record.withdrawn_at is None:
        record.withdrawn_at = timezone.now()
        record.save(update_fields=["withdrawn_at"])
        record_client_event(
            ClientActivityEventType.CONSENT_WITHDRAWN,
            actor=actor,
            client=client,
        )
    return record


def reinstate_consent(*, client: Client, actor: User) -> ConsentRecord:
    """Restore a withdrawn consent without treating it as a new grant.

    The template stays the one the client originally accepted. Staff
    reinstatement is a client activity event. The client's own later
    `grant_consent` is the path that stamps a new template.
    """
    try:
        record = ConsentRecord.objects.get(client=client)
    except ConsentRecord.DoesNotExist:
        msg = "This client has never granted questionnaire consent."
        raise ConsentRequiredError(msg) from None
    if record.withdrawn_at is not None:
        record.withdrawn_at = None
        record.save(update_fields=["withdrawn_at"])
        record_client_event(
            ClientActivityEventType.CONSENT_REINSTATED,
            actor=actor,
            client=client,
        )
    return record


def activate_consent_template(template: ConsentTemplate) -> None:
    """Make `template` the one stamped at grant time."""
    with transaction.atomic():
        ConsentTemplate.objects.exclude(pk=template.pk).update(is_active=False)
        template.is_active = True
        template.save(update_fields=["is_active"])


class AssessmentFlowError(Exception):
    """Base class for `start_assessment`/`submit_answer` failures."""


class ConsentRequiredError(AssessmentFlowError):
    """No effective `ConsentRecord` exists yet for this client."""


class QuestionnaireNotConfiguredError(AssessmentFlowError):
    """No default questionnaire has an active version."""


class AssessmentCompleteError(AssessmentFlowError):
    """The assessment is already completed; there is no current question."""


class QuestionMismatchError(AssessmentFlowError):
    """The submitted question is not the session's current position."""

    def __init__(self, current_question_id: UUID | None) -> None:
        self.current_question_id = current_question_id
        super().__init__(
            "Submitted question does not match the session's current position.",
        )


@dataclass(frozen=True)
class SessionState:
    next_question: Question | None
    answered_count: int
    total_count: int
    is_new_section: bool
    next_questions: tuple[Question, ...] = ()

    @property
    def completed(self) -> bool:
        return self.next_question is None


def _answers_by_question(session: QuestionnaireSession) -> dict[UUID, Answer]:
    answers = (
        Answer.objects.filter(session=session)
        .select_related("question")
        .prefetch_related("selected_options")
    )
    return {answer.question_id: answer for answer in answers}


def _last_answered_question(
    answer_by_question: dict[UUID, typing.Any],
) -> Question | None:
    """The question behind the most recently recorded answer.

    Answers are create-only and given in walk order, so the latest row is
    the question the respondent was on before `next_question`. Derived from
    the answers so a resume is correct: `current_question` still points at
    the unanswered question about to be served.
    """
    if not answer_by_question:
        return None
    return max(answer_by_question.values(), key=lambda answer: answer.created).question


def compute_session_state(session: QuestionnaireSession) -> SessionState:
    """Walk the assessment's own version, not whichever version is live now."""
    return state_from_answers(
        session.assessment.questionnaire_version,
        _answers_by_question(session),
    )


def state_from_answers(
    version: QuestionnaireVersion,
    answer_by_question: dict[UUID, typing.Any],
) -> SessionState:
    """The position reached by walking `version` with the given answers."""
    next_question, answered_count, total_count = routing.walk(
        version,
        answer_by_question,
    )
    previous_question = _last_answered_question(answer_by_question)
    is_new_section, next_questions = routing.presentation_state(
        next_question,
        previous_question,
        version,
    )
    return SessionState(
        next_question=next_question,
        next_questions=next_questions,
        answered_count=answered_count,
        total_count=total_count,
        is_new_section=is_new_section,
    )


def activate_version(version: QuestionnaireVersion) -> None:
    """Make `version` the one served, for this questionnaire only.

    Refuses a version whose graph `routing.walk` cannot follow. Clears
    `is_draft` in the same save: a row cannot be both draft and active.
    Fills `number` only when it is still null, one past the highest
    already-numbered version of this questionnaire.
    """
    if version.routing_model not in (RoutingModel.GRAPH, RoutingModel.EXTERNAL):
        msg = f"{version.name} routes by sequence, which can no longer be activated."
        raise routing.RoutingError(msg)
    if version.routing_model == RoutingModel.GRAPH:
        routing.validate_edges(version)
    with transaction.atomic():
        QuestionnaireVersion.objects.filter(
            questionnaire_id=version.questionnaire_id,
        ).exclude(pk=version.pk).update(is_active=False)
        version.is_active = True
        version.is_draft = False
        update_fields = ["is_active", "is_draft"]
        if version.number is None:
            highest = QuestionnaireVersion.objects.filter(
                questionnaire_id=version.questionnaire_id,
                number__isnull=False,
            ).aggregate(highest=Max("number"))["highest"]
            version.number = (highest or 0) + 1
            update_fields.append("number")
        version.save(update_fields=update_fields)


def _schedule_break_scoring(assessment: Assessment) -> None:
    """Ask BREAK for a score after this transaction commits.

    The answers are already stored. A failed call must not roll them back,
    and it must not invent a result. The task persists a row only when
    BREAK answers successfully.
    """
    assessment_id = str(assessment.pk)

    def _enqueue() -> None:
        enqueue_child_task(score_assessment_task, assessment_id)

    transaction.on_commit(_enqueue)


def start_assessment(
    *,
    client: Client,
) -> tuple[Assessment, QuestionnaireSession, SessionState]:
    """Consent-gate, then create or resume this client's assessment.

    Serves the default questionnaire's active version. An in-flight
    assessment stays on the version it started, because later reads go
    through `compute_session_state`.
    """
    if not ConsentRecord.objects.filter(
        client=client,
        withdrawn_at__isnull=True,
    ).exists():
        msg = "Consent is required before starting the questionnaire."
        raise ConsentRequiredError(msg)

    now = timezone.now()
    with transaction.atomic():
        try:
            active_version = QuestionnaireVersion.objects.get(
                questionnaire__is_default=True,
                is_active=True,
            )
        except QuestionnaireVersion.DoesNotExist as exc:
            msg = "No active questionnaire is currently configured."
            raise QuestionnaireNotConfiguredError(msg) from exc
        assessment, _created = Assessment.objects.get_or_create(
            client=client,
            defaults={
                "questionnaire_version": active_version,
                "status": AssessmentStatus.NOT_STARTED,
            },
        )
        session, _created = QuestionnaireSession.objects.get_or_create(
            assessment=assessment,
            defaults={"started_at": now, "last_activity_at": now},
        )
        if assessment.status == AssessmentStatus.NOT_STARTED:
            assessment.status = AssessmentStatus.IN_PROGRESS
            assessment.started_at = now
            assessment.save(update_fields=["status", "started_at", "modified"])
            record_assessment_event(
                AssessmentActivityEventType.STARTED,
                client=client,
            )

        state = compute_session_state(session)
        next_id = state.next_question.id if state.next_question else None
        if session.current_question_id != next_id:
            session.current_question = state.next_question
            session.save(update_fields=["current_question"])
    return assessment, session, state


def resolve_current_question(
    session: QuestionnaireSession,
    question_id: UUID,
) -> Question:
    """Validate `question_id` against the session's current position."""
    if session.assessment.status == AssessmentStatus.COMPLETED:
        msg = "This assessment has already been completed."
        raise AssessmentCompleteError(msg)
    if session.current_question_id != question_id:
        raise QuestionMismatchError(current_question_id=session.current_question_id)
    assert session.current_question is not None
    return session.current_question


def answer_defaults(question: Question, validated_data: dict) -> dict:
    """Keep only the field that matches `question.answer_type`."""
    if question.answer_type == AnswerTypeChoices.SINGLE_CHOICE:
        return {"selected_option": validated_data.get("selected_option")}
    if question.answer_type == AnswerTypeChoices.FREE_TEXT:
        return {"free_text_value": validated_data.get("free_text_value")}
    if question.answer_type == AnswerTypeChoices.SCALE:
        return {"scale_value": validated_data.get("scale_value")}
    return {}


def submit_answer(
    *,
    session: QuestionnaireSession,
    question: Question,
    validated_data: dict,
) -> SessionState:
    """Record one answer and advance the walk.

    Answers are immutable. A duplicate create for the same question, from
    a double-submit that raced past the position check, returns the state
    the winning request left. Any other integrity error is re-raised.

    Option ownership is the serializer's job. This function does not
    re-check it.
    """
    resolve_current_question(session, question.id)

    now = timezone.now()
    presented_at = session.last_activity_at
    with transaction.atomic():
        try:
            with transaction.atomic():
                answer = Answer.objects.create(
                    session=session,
                    question=question,
                    answered_at=now,
                    seconds_taken=(now - presented_at).total_seconds(),
                    **answer_defaults(question, validated_data),
                )
        except IntegrityError:
            if Answer.objects.filter(session=session, question=question).exists():
                return compute_session_state(session)
            raise
        if question.answer_type == AnswerTypeChoices.MULTI_CHOICE:
            answer.selected_options.set(validated_data.get("selected_options") or [])

        session.last_activity_at = now
        state = compute_session_state(session)
        if state.next_question is not None:
            session.current_question = state.next_question
            session.save(update_fields=["current_question", "last_activity_at"])
        else:
            session.current_question = None
            session.completed_at = now
            session.save(
                update_fields=["current_question", "completed_at", "last_activity_at"],
            )
            assessment = session.assessment
            assessment.status = AssessmentStatus.COMPLETED
            assessment.completed_at = now
            assessment.save(update_fields=["status", "completed_at", "modified"])
            record_assessment_event(
                AssessmentActivityEventType.COMPLETED,
                client=assessment.client,
            )
            _schedule_break_scoring(assessment)
    return state


def submit_answers(
    *,
    session: QuestionnaireSession,
    answers: list[tuple[Question, dict]],
) -> SessionState:
    """Record a batch atomically. A mismatch midway saves nothing."""
    if not answers:
        msg = "submit_answers requires a non-empty batch."
        raise AssessmentFlowError(msg)
    with transaction.atomic():
        first_question, first_data = answers[0]
        state = submit_answer(
            session=session,
            question=first_question,
            validated_data=first_data,
        )
        for question, validated_data in answers[1:]:
            state = submit_answer(
                session=session,
                question=question,
                validated_data=validated_data,
            )
        return state
