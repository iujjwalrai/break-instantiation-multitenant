from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from break_instantiation_backend.audit.models import AssessmentActivityEvent
from break_instantiation_backend.audit.models import AssessmentActivityEventType
from break_instantiation_backend.audit.models import ClientActivityEvent
from break_instantiation_backend.audit.models import ClientActivityEventType
from break_instantiation_backend.clients.tests.factories import ClientFactory
from break_instantiation_backend.questionnaires.models import Answer
from break_instantiation_backend.questionnaires.models import AnswerTypeChoices
from break_instantiation_backend.questionnaires.models import Assessment
from break_instantiation_backend.questionnaires.models import AssessmentStatus
from break_instantiation_backend.questionnaires.routing import RoutingCycleError
from break_instantiation_backend.questionnaires.services import AssessmentCompleteError
from break_instantiation_backend.questionnaires.services import ConsentRequiredError
from break_instantiation_backend.questionnaires.services import QuestionMismatchError
from break_instantiation_backend.questionnaires.services import (
    QuestionnaireNotConfiguredError,
)
from break_instantiation_backend.questionnaires.services import (
    activate_consent_template,
)
from break_instantiation_backend.questionnaires.services import activate_version
from break_instantiation_backend.questionnaires.services import compute_session_state
from break_instantiation_backend.questionnaires.services import grant_consent
from break_instantiation_backend.questionnaires.services import reinstate_consent
from break_instantiation_backend.questionnaires.services import start_assessment
from break_instantiation_backend.questionnaires.services import submit_answer
from break_instantiation_backend.questionnaires.services import submit_answers
from break_instantiation_backend.questionnaires.services import withdraw_consent
from break_instantiation_backend.questionnaires.tests.factories import AnswerFactory
from break_instantiation_backend.questionnaires.tests.factories import AssessmentFactory
from break_instantiation_backend.questionnaires.tests.factories import (
    ConsentRecordFactory,
)
from break_instantiation_backend.questionnaires.tests.factories import (
    ConsentTemplateFactory,
)
from break_instantiation_backend.questionnaires.tests.factories import EdgeFactory
from break_instantiation_backend.questionnaires.tests.factories import QuestionFactory
from break_instantiation_backend.questionnaires.tests.factories import (
    QuestionnaireFactory,
)
from break_instantiation_backend.questionnaires.tests.factories import (
    QuestionnaireSessionFactory,
)
from break_instantiation_backend.questionnaires.tests.factories import (
    QuestionnaireVersionFactory,
)
from break_instantiation_backend.questionnaires.tests.factories import (
    QuestionOptionFactory,
)
from break_instantiation_backend.results.models import AssessmentResult
from break_instantiation_backend.users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db

TWO_QUESTIONS = 2
ONE_QUESTION = 1
ONE_ANSWERED = 1


def _create_question(version, *, order, code, answer_type=AnswerTypeChoices.SCALE):
    return QuestionFactory.create(
        questionnaire_version=version,
        display_order=order,
        code=code,
        answer_type=answer_type,
        prompt=f"Prompt {code}",
    )


def _seed_two_question_session():
    version = QuestionnaireVersionFactory.create(is_active=True)
    q1 = _create_question(version, order=1, code="q1")
    q2 = _create_question(
        version,
        order=2,
        code="q2",
        answer_type=AnswerTypeChoices.FREE_TEXT,
    )
    EdgeFactory.create(from_question=q1, to_question=q2, priority=0)
    client = ClientFactory.create()
    ConsentRecordFactory.create(client=client)
    _assessment, session, _state = start_assessment(client=client)
    return session, q1, q2


def test_walk_starts_at_the_first_question_and_counts_both():
    version = QuestionnaireVersionFactory.create()
    q1 = _create_question(version, order=1, code="q1")
    _create_question(version, order=2, code="q2")
    EdgeFactory.create(
        from_question=q1,
        to_question=version.questions.get(code="q2"),
        priority=0,
    )
    assessment = AssessmentFactory.create(questionnaire_version=version)
    session = QuestionnaireSessionFactory.create(assessment=assessment)

    state = compute_session_state(session)

    assert state.next_question == q1
    assert state.answered_count == 0
    assert state.total_count == TWO_QUESTIONS
    assert state.completed is False


def test_a_branch_skips_the_question_the_edge_does_not_name():
    version = QuestionnaireVersionFactory.create()
    q1 = _create_question(
        version,
        order=1,
        code="q1",
        answer_type=AnswerTypeChoices.SINGLE_CHOICE,
    )
    option = QuestionOptionFactory.create(question=q1, code="yes")
    _create_question(version, order=2, code="q2")
    q3 = _create_question(version, order=3, code="q3")
    EdgeFactory.create(from_question=q1, from_option=option, to_question=q3, priority=0)
    assessment = AssessmentFactory.create(questionnaire_version=version)
    session = QuestionnaireSessionFactory.create(assessment=assessment)
    AnswerFactory.create(session=session, question=q1, selected_option=option)

    state = compute_session_state(session)

    assert state.next_question == q3
    assert state.answered_count == ONE_ANSWERED
    assert state.total_count == TWO_QUESTIONS


def test_an_edge_to_nothing_ends_the_flow():
    version = QuestionnaireVersionFactory.create()
    q1 = _create_question(
        version,
        order=1,
        code="q1",
        answer_type=AnswerTypeChoices.FREE_TEXT,
    )
    _create_question(version, order=2, code="q2")
    EdgeFactory.create(from_question=q1, to_question=None, priority=0)
    assessment = AssessmentFactory.create(questionnaire_version=version)
    session = QuestionnaireSessionFactory.create(assessment=assessment)
    AnswerFactory.create(session=session, question=q1, free_text_value="anything")

    state = compute_session_state(session)

    assert state.completed is True
    assert state.total_count == ONE_QUESTION


def test_activate_version_refuses_a_cycle():
    version = QuestionnaireVersionFactory.create()
    q1 = _create_question(version, order=1, code="q1")
    q2 = _create_question(version, order=2, code="q2")
    EdgeFactory.create(from_question=q1, to_question=q2, priority=0)
    EdgeFactory.create(from_question=q2, to_question=q1, priority=0)

    with pytest.raises(RoutingCycleError):
        activate_version(version)

    version.refresh_from_db()
    assert version.is_active is False


def test_activate_version_numbers_an_unnumbered_version_and_retires_the_previous():
    previous = QuestionnaireVersionFactory.create(is_active=True, number=1)
    nxt = QuestionnaireVersionFactory.create()
    question = _create_question(nxt, order=1, code="only")
    EdgeFactory.create(from_question=question, to_question=None, priority=0)

    activate_version(nxt)

    previous.refresh_from_db()
    nxt.refresh_from_db()
    assert previous.is_active is False
    assert nxt.is_active is True
    assert nxt.number == previous.number + 1


def test_activate_version_leaves_another_questionnaires_live_version_alone():
    other = QuestionnaireFactory.create(code="other", is_default=False)
    other_live = QuestionnaireVersionFactory.create(
        questionnaire=other,
        is_active=True,
        number=1,
    )
    version = QuestionnaireVersionFactory.create()
    question = _create_question(version, order=1, code="only")
    EdgeFactory.create(from_question=question, to_question=None, priority=0)

    activate_version(version)

    other_live.refresh_from_db()
    assert other_live.is_active is True


def test_grant_consent_is_idempotent_and_records_one_event():
    client = ClientFactory.create()
    template = ConsentTemplateFactory.create(is_active=True)

    first = grant_consent(client=client)
    second = grant_consent(client=client)

    assert first.pk == second.pk
    assert first.template == template
    assert (
        AssessmentActivityEvent.objects.filter(
            client=client,
            event_type=AssessmentActivityEventType.CONSENT_GRANTED,
        ).count()
        == 1
    )


def test_activate_consent_template_deactivates_the_previous_one():
    old = ConsentTemplateFactory.create(is_active=True)
    new = ConsentTemplateFactory.create(is_active=False)

    activate_consent_template(new)

    old.refresh_from_db()
    new.refresh_from_db()
    assert old.is_active is False
    assert new.is_active is True


def test_withdraw_consent_records_a_client_activity_event():
    client = ClientFactory.create()
    actor = UserFactory.create()
    grant_consent(client=client)

    record = withdraw_consent(client=client, actor=actor)

    assert record.withdrawn_at is not None
    event = ClientActivityEvent.objects.get(client=client)
    assert event.event_type == ClientActivityEventType.CONSENT_WITHDRAWN
    assert event.actor_user == actor
    assert (
        AssessmentActivityEvent.objects.filter(
            client=client,
            event_type=AssessmentActivityEventType.CONSENT_GRANTED,
        ).count()
        == 1
    )


def test_withdraw_consent_twice_does_not_record_a_second_event():
    client = ClientFactory.create()
    actor = UserFactory.create()
    grant_consent(client=client)
    withdraw_consent(client=client, actor=actor)

    withdraw_consent(client=client, actor=actor)

    assert (
        ClientActivityEvent.objects.filter(
            client=client,
            event_type=ClientActivityEventType.CONSENT_WITHDRAWN,
        ).count()
        == 1
    )


def test_withdraw_consent_without_a_grant_raises():
    client = ClientFactory.create()
    actor = UserFactory.create()

    with pytest.raises(ConsentRequiredError):
        withdraw_consent(client=client, actor=actor)


def test_client_regrant_after_withdrawal_is_an_assessment_event():
    client = ClientFactory.create()
    actor = UserFactory.create()
    first = ConsentTemplateFactory.create(is_active=True, text="First")
    grant_consent(client=client)
    withdraw_consent(client=client, actor=actor)
    second = ConsentTemplateFactory.create(is_active=False, text="Second")
    activate_consent_template(second)

    record = grant_consent(client=client)

    assert record.withdrawn_at is None
    assert record.template == second
    assert record.template != first
    assert (
        AssessmentActivityEvent.objects.filter(
            client=client,
            event_type=AssessmentActivityEventType.CONSENT_GRANTED,
        ).count()
        == 2  # noqa: PLR2004
    )
    assert not ClientActivityEvent.objects.filter(
        event_type=ClientActivityEventType.CONSENT_REINSTATED,
    ).exists()


def test_staff_reinstate_keeps_the_original_template_and_records_client_activity():
    client = ClientFactory.create()
    actor = UserFactory.create()
    template = ConsentTemplateFactory.create(is_active=True, text="Original")
    grant_consent(client=client)
    withdraw_consent(client=client, actor=actor)
    newer = ConsentTemplateFactory.create(is_active=False, text="Newer")
    activate_consent_template(newer)

    record = reinstate_consent(client=client, actor=actor)

    assert record.withdrawn_at is None
    assert record.template == template
    event = ClientActivityEvent.objects.get(
        client=client,
        event_type=ClientActivityEventType.CONSENT_REINSTATED,
    )
    assert event.actor_user == actor
    assert (
        AssessmentActivityEvent.objects.filter(
            client=client,
            event_type=AssessmentActivityEventType.CONSENT_GRANTED,
        ).count()
        == 1
    )


def test_start_requires_consent_and_a_live_default_version():
    client = ClientFactory.create()
    with pytest.raises(ConsentRequiredError):
        start_assessment(client=client)

    grant_consent(client=client)
    with pytest.raises(QuestionnaireNotConfiguredError):
        start_assessment(client=client)


def test_start_is_refused_after_withdrawal_and_allowed_after_reinstate():
    client = ClientFactory.create()
    actor = UserFactory.create()
    version = QuestionnaireVersionFactory.create(is_active=True)
    question = _create_question(version, order=1, code="q1")
    EdgeFactory.create(from_question=question, to_question=None, priority=0)
    grant_consent(client=client)
    withdraw_consent(client=client, actor=actor)

    with pytest.raises(ConsentRequiredError):
        start_assessment(client=client)

    reinstate_consent(client=client, actor=actor)
    _assessment, session, state = start_assessment(client=client)

    assert state.next_question == question
    assert session.assessment.status == AssessmentStatus.IN_PROGRESS


def test_start_resumes_without_a_second_started_event():
    session, q1, _q2 = _seed_two_question_session()
    client = session.assessment.client

    _assessment, resumed, state = start_assessment(client=client)

    assert resumed.pk == session.pk
    assert state.next_question == q1
    assert (
        AssessmentActivityEvent.objects.filter(
            client=client,
            event_type=AssessmentActivityEventType.STARTED,
        ).count()
        == 1
    )


def test_submit_answer_advances_and_stores_seconds_taken(monkeypatch):
    session, q1, q2 = _seed_two_question_session()
    presented = timezone.now()
    session.last_activity_at = presented
    session.save(update_fields=["last_activity_at"])

    class _Frozen:
        @staticmethod
        def now():
            return presented + timedelta(seconds=5)

    monkeypatch.setattr(
        "break_instantiation_backend.questionnaires.services.timezone",
        _Frozen,
    )

    state = submit_answer(
        session=session,
        question=q1,
        validated_data={"scale_value": 3},
    )

    answer = Answer.objects.get(session=session, question=q1)
    assert answer.scale_value == 3  # noqa: PLR2004
    assert answer.seconds_taken == 5  # noqa: PLR2004
    assert state.next_question == q2


def test_submit_answer_rejects_a_question_that_is_not_current():
    session, _q1, q2 = _seed_two_question_session()

    with pytest.raises(QuestionMismatchError):
        submit_answer(
            session=session,
            question=q2,
            validated_data={"free_text_value": "too soon"},
        )

    assert not Answer.objects.filter(session=session).exists()


def test_submit_answers_rolls_back_the_batch_when_a_later_item_mismatches():
    session, q1, _q2 = _seed_two_question_session()

    with pytest.raises(QuestionMismatchError):
        submit_answers(
            session=session,
            answers=[
                (q1, {"scale_value": 1}),
                (q1, {"scale_value": 2}),
            ],
        )

    assert not Answer.objects.filter(session=session).exists()
    session.refresh_from_db()
    assert session.current_question == q1


def test_finishing_records_completed_and_does_not_invent_a_score(
    django_capture_on_commit_callbacks,
):
    session, q1, q2 = _seed_two_question_session()
    submit_answer(session=session, question=q1, validated_data={"scale_value": 1})
    session.refresh_from_db()

    with django_capture_on_commit_callbacks(execute=True):
        state = submit_answer(
            session=session,
            question=q2,
            validated_data={"free_text_value": "done"},
        )

    assert state.completed is True
    assessment = Assessment.objects.get(pk=session.assessment_id)
    assert assessment.status == AssessmentStatus.COMPLETED
    assert not AssessmentResult.objects.filter(assessment=assessment).exists()
    assert AssessmentActivityEvent.objects.filter(
        client=assessment.client,
        event_type=AssessmentActivityEventType.COMPLETED,
    ).exists()
    assert AssessmentActivityEvent.objects.filter(
        client=assessment.client,
        event_type=AssessmentActivityEventType.SCORING_FAILED,
    ).exists()


def test_submit_answer_after_completion_raises():
    session, q1, q2 = _seed_two_question_session()
    submit_answer(session=session, question=q1, validated_data={"scale_value": 1})
    session.refresh_from_db()
    submit_answer(
        session=session,
        question=q2,
        validated_data={"free_text_value": "done"},
    )
    session.refresh_from_db()

    with pytest.raises(AssessmentCompleteError):
        submit_answer(
            session=session,
            question=q2,
            validated_data={"free_text_value": "again"},
        )
