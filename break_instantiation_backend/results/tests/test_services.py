from __future__ import annotations

import json
from io import BytesIO
from urllib.error import HTTPError
from urllib.error import URLError

import pytest

from break_instantiation_backend.audit.models import AssessmentActivityEvent
from break_instantiation_backend.audit.models import AssessmentActivityEventType
from break_instantiation_backend.clients.tests.factories import ClientFactory
from break_instantiation_backend.questionnaires.models import AnswerTypeChoices
from break_instantiation_backend.questionnaires.models import AssessmentStatus
from break_instantiation_backend.questionnaires.tests.factories import AnswerFactory
from break_instantiation_backend.questionnaires.tests.factories import AssessmentFactory
from break_instantiation_backend.questionnaires.tests.factories import QuestionFactory
from break_instantiation_backend.questionnaires.tests.factories import (
    QuestionnaireSessionFactory,
)
from break_instantiation_backend.questionnaires.tests.factories import (
    QuestionOptionFactory,
)
from break_instantiation_backend.results.models import AssessmentResult
from break_instantiation_backend.results.services import answer_responses
from break_instantiation_backend.results.services import score_completed_assessment

pytestmark = pytest.mark.django_db


class _Body:
    def __init__(self, status: int, payload: object) -> None:
        self.status = status
        self._payload = payload

    def read(self) -> bytes:
        if self._payload is None:
            return b""
        return json.dumps(self._payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def _completed_assessment():
    client = ClientFactory.create()
    assessment = AssessmentFactory.create(
        client=client,
        status=AssessmentStatus.COMPLETED,
    )
    session = QuestionnaireSessionFactory.create(assessment=assessment)
    question = QuestionFactory.create(
        questionnaire_version=assessment.questionnaire_version,
        prompt="How are you?",
        code="mood",
        answer_type=AnswerTypeChoices.SINGLE_CHOICE,
        display_order=1,
    )
    option = QuestionOptionFactory.create(question=question, label="Fine", code="fine")
    AnswerFactory.create(
        session=session,
        question=question,
        selected_option=option,
    )
    return assessment


def test_answer_responses_key_choice_labels_by_prompt():
    assessment = _completed_assessment()

    payload = answer_responses(assessment)

    assert payload == {"How are you?": "Fine"}


def test_success_stores_the_break_body_and_nothing_else(settings, monkeypatch):
    settings.BREAK_BACKEND_BASE_URL = "https://break.example"
    settings.BREAK_SCORING_TOKEN = "svc-token"  # noqa: S105
    assessment = _completed_assessment()
    body = {
        "profile": "steady",
        "missing_questions": ["q9"],
    }

    def _open(request, timeout):
        assert request.get_header("Authorization") == "Token svc-token"
        assert json.loads(request.data)["responses"]["How are you?"] == "Fine"
        return _Body(200, body)

    monkeypatch.setattr(
        "break_instantiation_backend.results.break_client.urllib.request.urlopen",
        _open,
    )

    result = score_completed_assessment(str(assessment.pk))

    assert result is not None
    assert result.payload == body
    assert result.http_status == 200  # noqa: PLR2004
    assert result.client_id == assessment.client_id
    assert "bvi_risk" not in result.payload
    assert AssessmentResult.objects.count() == 1
    assert AssessmentActivityEvent.objects.filter(
        client=assessment.client,
        event_type=AssessmentActivityEventType.RESULT_STORED,
    ).exists()


def test_a_second_success_does_not_call_break_again(settings, monkeypatch):
    settings.BREAK_BACKEND_BASE_URL = "https://break.example"
    settings.BREAK_SCORING_TOKEN = "svc-token"  # noqa: S105
    assessment = _completed_assessment()
    calls = {"n": 0}

    def _open(request, timeout):
        calls["n"] += 1
        return _Body(200, {"profile": "steady"})

    monkeypatch.setattr(
        "break_instantiation_backend.results.break_client.urllib.request.urlopen",
        _open,
    )

    first = score_completed_assessment(str(assessment.pk))
    second = score_completed_assessment(str(assessment.pk))

    assert first.pk == second.pk
    assert calls["n"] == 1
    assert (
        AssessmentActivityEvent.objects.filter(
            event_type=AssessmentActivityEventType.RESULT_STORED,
        ).count()
        == 1
    )


@pytest.mark.parametrize(
    "failure",
    [
        HTTPError(
            url="https://break.example",
            code=503,
            msg="down",
            hdrs=None,
            fp=BytesIO(b'{"score": 99}'),
        ),
        URLError("timed out"),
    ],
)
def test_failure_leaves_no_result(settings, monkeypatch, failure):
    settings.BREAK_BACKEND_BASE_URL = "https://break.example"
    settings.BREAK_SCORING_TOKEN = "svc-token"  # noqa: S105
    assessment = _completed_assessment()

    def _open(request, timeout):
        raise failure

    monkeypatch.setattr(
        "break_instantiation_backend.results.break_client.urllib.request.urlopen",
        _open,
    )

    result = score_completed_assessment(str(assessment.pk))

    assert result is None
    assert not AssessmentResult.objects.exists()
    assert AssessmentActivityEvent.objects.filter(
        client=assessment.client,
        event_type=AssessmentActivityEventType.SCORING_FAILED,
    ).exists()
    assert not AssessmentActivityEvent.objects.filter(
        event_type=AssessmentActivityEventType.RESULT_STORED,
    ).exists()


def test_unconfigured_scoring_stores_nothing(monkeypatch):
    assessment = _completed_assessment()

    def _open(request, timeout):
        msg = "should not be called"
        raise AssertionError(msg)

    monkeypatch.setattr(
        "break_instantiation_backend.results.break_client.urllib.request.urlopen",
        _open,
    )

    result = score_completed_assessment(str(assessment.pk))

    assert result is None
    assert not AssessmentResult.objects.exists()
    assert AssessmentActivityEvent.objects.filter(
        event_type=AssessmentActivityEventType.SCORING_FAILED,
    ).exists()


def test_an_incomplete_assessment_is_not_scored(settings, monkeypatch):
    settings.BREAK_BACKEND_BASE_URL = "https://break.example"
    settings.BREAK_SCORING_TOKEN = "svc-token"  # noqa: S105
    assessment = AssessmentFactory.create(status=AssessmentStatus.IN_PROGRESS)

    def _open(request, timeout):
        msg = "should not be called"
        raise AssertionError(msg)

    monkeypatch.setattr(
        "break_instantiation_backend.results.break_client.urllib.request.urlopen",
        _open,
    )

    assert score_completed_assessment(str(assessment.pk)) is None
    assert not AssessmentResult.objects.exists()
