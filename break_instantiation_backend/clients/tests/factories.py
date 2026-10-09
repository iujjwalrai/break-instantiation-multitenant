from __future__ import annotations

from datetime import timedelta

from django.utils import timezone
from factory import Faker
from factory import LazyFunction
from factory import SubFactory
from factory.django import DjangoModelFactory

from break_instantiation_backend.clients.models import Client
from break_instantiation_backend.clients.models import ClientPortalInvite
from break_instantiation_backend.clients.models import ClientSession
from break_instantiation_backend.clients.models import ClientUser
from break_instantiation_backend.clients.models import MagicLoginToken
from break_instantiation_backend.tokens import generate_token
from break_instantiation_backend.tokens import hash_token
from break_instantiation_backend.users.tests.factories import UserFactory


class ClientUserFactory(DjangoModelFactory[ClientUser]):
    email = Faker("email")

    class Meta:
        model = ClientUser
        django_get_or_create = ["email"]


class ClientFactory(DjangoModelFactory[Client]):
    full_name = Faker("name")
    email = Faker("email")

    class Meta:
        model = Client
        django_get_or_create = ["email"]


class ClientPortalInviteFactory(DjangoModelFactory[ClientPortalInvite]):
    invited_email = Faker("email")
    invited_by = SubFactory(UserFactory)
    target_client = SubFactory(ClientFactory)
    token_hash = LazyFunction(lambda: hash_token(generate_token()))
    expires_at = LazyFunction(lambda: timezone.now() + timedelta(days=7))

    class Meta:
        model = ClientPortalInvite


class MagicLoginTokenFactory(DjangoModelFactory[MagicLoginToken]):
    client_user = SubFactory(ClientUserFactory)
    token_hash = LazyFunction(lambda: hash_token(generate_token()))
    expires_at = LazyFunction(lambda: timezone.now() + timedelta(minutes=15))

    class Meta:
        model = MagicLoginToken


class ClientSessionFactory(DjangoModelFactory[ClientSession]):
    client_user = SubFactory(ClientUserFactory)
    token_hash = LazyFunction(lambda: hash_token(generate_token()))
    expires_at = LazyFunction(lambda: timezone.now() + timedelta(minutes=30))
    last_used_at = LazyFunction(timezone.now)

    class Meta:
        model = ClientSession
