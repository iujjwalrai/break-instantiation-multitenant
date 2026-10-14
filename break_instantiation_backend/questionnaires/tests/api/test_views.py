from __future__ import annotations

import json
from http import HTTPStatus

import pytest
from django.urls import reverse
from django.utils import timezone

from break_instantiation_backend.clients.tests.factories import ClientFactory
from break_instantiation_backend.clients.tests.factories import ClientSessionFactory
from break_instantiation_backend.clients.tests.factories import ClientUserFactory
from break_instantiation_backend.questionnaires.models import Answer
from break_instantiation_backend.questionnaires.models import AnswerTypeChoices
from break_instantiation_backend.questionnaires.models import ConsentRecord
from break_instantiation_backend.questionnaires.tests.factories import (
    ConsentRecordFactory,
)
from break_instantiation_backend.questionnaires.tests.factories import (
    ConsentTemplateFactory,
)
from break_instantiation_backend.questionnaires.tests.factories import EdgeFactory
from break_instantiation_backend.questionnaires.tests.factories import QuestionFactory
from break_instantiation_backend.questionnaires.tests.factories import (
    QuestionnaireVersionFactory,
)
from break_instantiation_backend.questionnaires.tests.factories import (
    QuestionOptionFactory,
)
from break_instantiation_backend.tokens import generate_token
from break_instantiation_backend.tokens import hash_token

pytestmark = pytest.mark.django_db


def _post(client, url_name, data=None):
    return client.post(
        reverse(url_name),
        data=json.dumps(data or {}),
        content_type="application/json",
    )


def _authenticate(client):
    client_user = ClientUserFactory.create()
    target = ClientFactory.create(client_user=client_user)
    session = ClientSessionFactory.create(client_user=client_user)
    raw_token = generate_token()
    session.token_hash = hash_token(raw_token)
    session.save(update_fields=["token_hash"])
    client.cookies["client_session"] = raw_token
    return target


class TestConsent:
    def test_template_and_grant_require_a_session(self, client):
        assert (
            client.get(reverse("api:assessment:consent-template")).status_code
            == HTTPStatus.FORBIDDEN
        )
        assert (
            client.post(reverse("api:assessment:consent")).status_code
            == HTTPStatus.FORBIDDEN
        )

    def test_template_is_the_active_wording(self, client):
        _authenticate(client)
        ConsentTemplateFactory.create(is_active=False, text="Old", version="v0")
        active = ConsentTemplateFactory.create(
            is_active=True,
            text="Current",
            version="v1",
        )

        response = client.get(reverse("api:assessment:consent-template"))

        assert response.status_code == HTTPStatus.OK
        assert response.json()["text"] == "Current"
        assert response.json()["version"] == active.version

    def test_grant_stores_the_template_and_a_repeat_is_a_no_op(self, client):
        target = _authenticate(client)
        template = ConsentTemplateFactory.create(is_active=True, text="I agree.")

        first = client.post(reverse("api:assessment:consent"))
        second = client.post(reverse("api:assessment:consent"))

        assert first.status_code == HTTPStatus.OK
        assert second.status_code == HTTPStatus.OK
        assert first.json()["text"] == "I agree."
        assert first.json()["id"] == second.json()["id"]
        assert ConsentRecord.objects.get(client=target).template == template

    def test_get_is_404_until_granted_and_after_withdrawal(self, client):
        target = _authenticate(client)

        missing = client.get(reverse("api:assessment:consent"))
        assert missing.status_code == HTTPStatus.NOT_FOUND

        record = ConsentRecordFactory.create(
            client=target,
            withdrawn_at=timezone.now(),
        )
        withdrawn = client.get(reverse("api:assessment:consent"))
        assert withdrawn.status_code == HTTPStatus.NOT_FOUND

        record.withdrawn_at = None
        record.save(update_fields=["withdrawn_at"])
        granted = client.get(reverse("api:assessment:consent"))
        assert granted.status_code == HTTPStatus.OK
        assert granted.json()["id"] == str(record.pk)


class TestAssessmentWalk:
    def test_start_requires_consent(self, client):
        _authenticate(client)
        QuestionnaireVersionFactory.create(is_active=True)

        response = client.post(reverse("api:assessment:start"))

        assert response.status_code == HTTPStatus.FORBIDDEN

    def test_start_resume_and_branch(self, client):
        target = _authenticate(client)
        ConsentRecordFactory.create(client=target)
        version = QuestionnaireVersionFactory.create(is_active=True)
        q1 = QuestionFactory.create(
            questionnaire_version=version,
            display_order=1,
            code="q1",
            prompt="First?",
            answer_type=AnswerTypeChoices.SINGLE_CHOICE,
        )
        yes = QuestionOptionFactory.create(question=q1, code="yes", label="Yes")
        QuestionFactory.create(
            questionnaire_version=version,
            display_order=2,
            code="q2",
            prompt="Skipped",
            answer_type=AnswerTypeChoices.SCALE,
        )
        q3 = QuestionFactory.create(
            questionnaire_version=version,
            display_order=3,
            code="q3",
            prompt="Last?",
            answer_type=AnswerTypeChoices.FREE_TEXT,
        )
        EdgeFactory.create(
            from_question=q1,
            from_option=yes,
            to_question=q3,
            priority=0,
        )

        started = client.post(reverse("api:assessment:start"))
        assert started.status_code == HTTPStatus.OK
        assert started.json()["questions"][0]["code"] == "q1"
        assert started.json()["completed"] is False

        resumed = client.post(reverse("api:assessment:start"))
        same_question = started.json()["questions"][0]["id"]
        assert resumed.json()["questions"][0]["id"] == same_question

        answered = _post(
            client,
            "api:assessment:answers",
            {
                "answers": [
                    {
                        "question_id": str(q1.id),
                        "selected_option_id": str(yes.id),
                    },
                ],
            },
        )
        assert answered.status_code == HTTPStatus.OK
        assert answered.json()["questions"][0]["code"] == "q3"
        assert Answer.objects.filter(question=q1, selected_option=yes).exists()
        assert not Answer.objects.filter(question__code="q2").exists()

        finished = _post(
            client,
            "api:assessment:answers",
            {"answers": [{"question_id": str(q3.id), "free_text_value": "done"}]},
        )
        assert finished.status_code == HTTPStatus.OK
        assert finished.json()["completed"] is True
        assert finished.json()["assessment_status"] == "completed"
