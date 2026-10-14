from __future__ import annotations

import logging

from django.db import IntegrityError
from django.db import transaction
from django.utils import timezone

from break_instantiation_backend.audit.models import AssessmentActivityEventType
from break_instantiation_backend.audit.services import record_assessment_event
from break_instantiation_backend.questionnaires.models import Answer
from break_instantiation_backend.questionnaires.models import AnswerTypeChoices
from break_instantiation_backend.questionnaires.models import Assessment
from break_instantiation_backend.questionnaires.models import AssessmentStatus

from .break_client import BreakScoringError
from .break_client import score_responses
from .models import AssessmentResult

logger = logging.getLogger(__name__)


def answer_responses(assessment: Assessment) -> dict[str, str]:
    """Answers keyed by question prompt, the body BREAK's scorer expects.

    Choice answers are option labels, joined with ", " when several are
    selected, in display order. Free text and scale are included as their
    stored values so the call is not a partial walk. Unanswered questions
    are omitted; BREAK reports whatever it still considers missing.
    """
    answers = (
        Answer.objects.filter(session__assessment=assessment)
        .select_related("question", "selected_option")
        .prefetch_related("selected_options")
        .order_by("answered_at", "created")
    )
    payload: dict[str, str] = {}
    for answer in answers:
        payload[answer.question.prompt] = _rendered_answer(answer)
    return payload


def _rendered_answer(answer: Answer) -> str:
    question = answer.question
    if question.answer_type == AnswerTypeChoices.SINGLE_CHOICE:
        if answer.selected_option_id is None:
            return ""
        return answer.selected_option.label
    if question.answer_type == AnswerTypeChoices.MULTI_CHOICE:
        labels = answer.selected_options.order_by("display_order", "label").values_list(
            "label",
            flat=True,
        )
        return ", ".join(labels)
    if question.answer_type == AnswerTypeChoices.FREE_TEXT:
        return answer.free_text_value or ""
    if answer.scale_value is None:
        return ""
    return str(answer.scale_value)


def score_completed_assessment(assessment_id: str) -> AssessmentResult | None:
    """Call BREAK and persist the response only when the call succeeds.

    An existing result is left as it is. A failed call writes an audit
    event and no result row.
    """
    try:
        assessment = Assessment.objects.select_related("client").get(pk=assessment_id)
    except Assessment.DoesNotExist:
        logger.warning("Scoring skipped; assessment %s does not exist.", assessment_id)
        return None
    if assessment.status != AssessmentStatus.COMPLETED:
        return None

    existing = AssessmentResult.objects.filter(assessment=assessment).first()
    if existing is not None:
        return existing

    try:
        status_code, payload = score_responses(answer_responses(assessment))
    except BreakScoringError:
        logger.warning(
            "BREAK scoring failed for assessment %s.",
            assessment.pk,
            exc_info=True,
        )
        record_assessment_event(
            AssessmentActivityEventType.SCORING_FAILED,
            client=assessment.client,
        )
        return None

    try:
        with transaction.atomic():
            result = AssessmentResult.objects.create(
                assessment=assessment,
                client=assessment.client,
                payload=payload,
                http_status=status_code,
                scored_at=timezone.now(),
            )
            record_assessment_event(
                AssessmentActivityEventType.RESULT_STORED,
                client=assessment.client,
            )
    except IntegrityError:
        return AssessmentResult.objects.get(assessment=assessment)
    return result
