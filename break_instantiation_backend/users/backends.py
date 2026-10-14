import contextvars

from django.contrib.auth.backends import ModelBackend
from django.db import connection
from django_tenants.utils import get_public_schema_name
from django_tenants.utils import schema_context

from break_instantiation_backend.users.staff_auth import STAFF_HOME_SESSION_KEY

# Set by StaffHomeMiddleware from the session before auth loads the user.
# A context var keeps the public overseer distinct from a child user whose
# primary key happens to be the same integer.
staff_home_schema: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "staff_home_schema",
    default=None,
)


class StaffModelBackend(ModelBackend):
    """Load a public backend admin even when the request is on a child."""

    def authenticate(self, request, username=None, password=None, **kwargs):
        user = super().authenticate(
            request,
            username=username,
            password=password,
            **kwargs,
        )
        if user is not None:
            user._staff_schema = connection.schema_name  # noqa: SLF001
        return user

    def get_user(self, user_id):
        home = staff_home_schema.get()
        public = get_public_schema_name()
        if home == public and connection.schema_name != public:
            with schema_context(public):
                user = super().get_user(user_id)
            if user is not None:
                user._staff_schema = public  # noqa: SLF001
            return user
        user = super().get_user(user_id)
        if user is not None:
            user._staff_schema = connection.schema_name  # noqa: SLF001
        return user


__all__ = ["STAFF_HOME_SESSION_KEY", "StaffModelBackend", "staff_home_schema"]
