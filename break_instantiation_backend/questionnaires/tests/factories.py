from __future__ import annotations

from django.utils import timezone
from factory import LazyFunction
from factory import Sequence
from factory import SubFactory
from factory.django import DjangoModelFactory

from break_instantiation_backend.clients.tests.factories import ClientFactory
from break_instantiation_backend.questionnaires.models import Answer
from break_instantiation_backend.questionnaires.models import AnswerTypeChoices
from break_instantiation_backend.questionnaires.models import Assessment
from break_instantiation_backend.questionnaires.models import ConsentRecord
from break_instantiation_backend.questionnaires.models import ConsentTemplate
from break_instantiation_backend.questionnaires.models import Edge
from break_instantiation_backend.questionnaires.models import Question
from break_instantiation_backend.questionnaires.models import Questionnaire
from break_instantiation_backend.questionnaires.models import QuestionnaireSession
from break_instantiation_backend.questionnaires.models import QuestionnaireVersion
from break_instantiation_backend.questionnaires.models import QuestionOption
from break_instantiation_backend.questionnaires.models import Section


class QuestionnaireFactory(DjangoModelFactory[Questionnaire]):
    name = Sequence(lambda n: f"Questionnaire {n}")
    code = Sequence(lambda n: f"questionnaire-{n}")

    class Meta:
        model = Questionnaire
        django_get_or_create = ("code",)


def _default_questionnaire() -> Questionnaire:
    """One product shared by versions, so the live-version constraint is real."""
    questionnaire, _created = Questionnaire.objects.get_or_create(
        code="default",
        defaults={"name": "Default questionnaire", "is_default": True},
    )
    return questionnaire


class QuestionnaireVersionFactory(DjangoModelFactory[QuestionnaireVersion]):
    questionnaire = LazyFunction(_default_questionnaire)
    name = Sequence(lambda n: f"Questionnaire v{n}")

    class Meta:
        model = QuestionnaireVersion


class QuestionFactory(DjangoModelFactory[Question]):
    questionnaire_version = SubFactory(QuestionnaireVersionFactory)
    code = Sequence(lambda n: f"q{n}")
    prompt = Sequence(lambda n: f"Question prompt {n}")
    answer_type = AnswerTypeChoices.SINGLE_CHOICE
    display_order = Sequence(lambda n: n)

    class Meta:
        model = Question


class QuestionOptionFactory(DjangoModelFactory[QuestionOption]):
    question = SubFactory(QuestionFactory)
    code = Sequence(lambda n: f"opt{n}")
    label = Sequence(lambda n: f"Option {n}")
    display_order = Sequence(lambda n: n)

    class Meta:
        model = QuestionOption


class SectionFactory(DjangoModelFactory[Section]):
    questionnaire_version = SubFactory(QuestionnaireVersionFactory)
    code = Sequence(lambda n: f"section{n}")
    name = Sequence(lambda n: f"Section {n}")
    display_order = Sequence(lambda n: n)

    class Meta:
        model = Section


class EdgeFactory(DjangoModelFactory[Edge]):
    from_question = SubFactory(QuestionFactory)
    from_option = None
    to_question = None
    priority = Sequence(lambda n: n)

    class Meta:
        model = Edge


class AssessmentFactory(DjangoModelFactory[Assessment]):
    client = SubFactory(ClientFactory)
    questionnaire_version = SubFactory(QuestionnaireVersionFactory)

    class Meta:
        model = Assessment


class QuestionnaireSessionFactory(DjangoModelFactory[QuestionnaireSession]):
    assessment = SubFactory(AssessmentFactory)
    last_activity_at = LazyFunction(timezone.now)

    class Meta:
        model = QuestionnaireSession


class AnswerFactory(DjangoModelFactory[Answer]):
    session = SubFactory(QuestionnaireSessionFactory)
    question = SubFactory(QuestionFactory)

    class Meta:
        model = Answer


class ConsentTemplateFactory(DjangoModelFactory[ConsentTemplate]):
    version = Sequence(lambda n: f"v{n}")
    text = "Sample consent text."

    class Meta:
        model = ConsentTemplate


class ConsentRecordFactory(DjangoModelFactory[ConsentRecord]):
    client = SubFactory(ClientFactory)

    class Meta:
        model = ConsentRecord
