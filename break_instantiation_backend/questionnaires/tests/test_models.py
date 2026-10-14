from __future__ import annotations

import pytest
from django.db import IntegrityError
from django.db import transaction

from break_instantiation_backend.questionnaires.models import ConsentTemplate
from break_instantiation_backend.questionnaires.tests.factories import (
    ConsentTemplateFactory,
)
from break_instantiation_backend.questionnaires.tests.factories import (
    QuestionnaireVersionFactory,
)

pytestmark = pytest.mark.django_db


def test_consent_template_text_is_immutable_once_created():
    template = ConsentTemplateFactory.create(text="Original")

    template.text = "Changed"
    with pytest.raises(ValueError, match="immutable"):
        template.save()

    template.refresh_from_db()
    assert template.text == "Original"


def test_consent_template_allows_toggling_is_active():
    template = ConsentTemplateFactory.create(is_active=False)

    template.is_active = True
    template.save(update_fields=["is_active"])

    template.refresh_from_db()
    assert template.is_active is True


def test_only_one_consent_template_can_be_active():
    ConsentTemplateFactory.create(is_active=True)
    with pytest.raises(IntegrityError), transaction.atomic():
        ConsentTemplate.objects.create(
            version="other",
            text="Other wording.",
            is_active=True,
        )


def test_only_one_version_of_a_questionnaire_can_be_live():
    QuestionnaireVersionFactory.create(is_active=True)
    with pytest.raises(IntegrityError), transaction.atomic():
        QuestionnaireVersionFactory.create(is_active=True)
