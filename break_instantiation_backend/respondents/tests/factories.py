from __future__ import annotations

from datetime import timedelta

from django.utils import timezone
from factory import Faker
from factory import LazyFunction
from factory import SubFactory
from factory.django import DjangoModelFactory

from break_instantiation_backend.respondents.models import MagicLoginToken
from break_instantiation_backend.respondents.models import Respondent
from break_instantiation_backend.respondents.models import RespondentSession
from break_instantiation_backend.tokens import generate_token
from break_instantiation_backend.tokens import hash_token


class RespondentFactory(DjangoModelFactory[Respondent]):
    email = Faker("email")

    class Meta:
        model = Respondent
        django_get_or_create = ["email"]


class MagicLoginTokenFactory(DjangoModelFactory[MagicLoginToken]):
    respondent = SubFactory(RespondentFactory)
    token_hash = LazyFunction(lambda: hash_token(generate_token()))
    expires_at = LazyFunction(lambda: timezone.now() + timedelta(minutes=15))

    class Meta:
        model = MagicLoginToken


class RespondentSessionFactory(DjangoModelFactory[RespondentSession]):
    respondent = SubFactory(RespondentFactory)
    token_hash = LazyFunction(lambda: hash_token(generate_token()))
    expires_at = LazyFunction(lambda: timezone.now() + timedelta(minutes=30))
    last_used_at = LazyFunction(timezone.now)

    class Meta:
        model = RespondentSession
