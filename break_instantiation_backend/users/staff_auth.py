"""Staff sign-in that can see a public backend admin from a child host."""

from django.contrib.auth import authenticate
from django.contrib.auth import login
from django.db import connection
from django_tenants.utils import get_public_schema_name
from django_tenants.utils import schema_context

from break_instantiation_backend.users.models import User
from break_instantiation_backend.users.roles import StaffRole
from break_instantiation_backend.users.roles import can_sign_in

STAFF_HOME_SESSION_KEY = "staff_home"


class CrossSchemaInviteError(Exception):
    """`invited_by` has to be a user row in the same child."""


def user_in_current_schema(user: User) -> bool:
    """True when `user` is a row in the schema this connection is using."""
    home = getattr(user, "_staff_schema", None)
    if home is not None and home != connection.schema_name:
        return False
    if not getattr(user, "pk", None):
        return False
    return User.objects.filter(pk=user.pk, email__iexact=user.email).exists()


def _may_sign_in_here(user: User) -> bool:
    """A `backend_admin` row in a child schema is not the public overseer."""
    if (
        user.role == StaffRole.BACKEND_ADMIN
        and connection.schema_name != get_public_schema_name()
    ):
        return False
    return can_sign_in(user)


def authenticate_staff(
    request,
    email: str,
    password: str,
) -> tuple[User | None, User | None]:
    """Return `(account, signed_in_user)`.

    A customer admin in the current schema wins over a public overseer
    with the same email. `account` is set when a row was found, so a
    wrong password can be audited. The second value is set only when
    the password matches and that account may sign in here.
    """
    local = User.objects.filter(email__iexact=email).first()
    if local is not None:
        authenticated = authenticate(request, email=local.email, password=password)
        if authenticated is not None and _may_sign_in_here(authenticated):
            return local, authenticated
        return local, None

    public = get_public_schema_name()
    if connection.schema_name == public:
        User().set_password(password)
        return None, None

    with schema_context(public):
        public_user = User.objects.filter(email__iexact=email).first()
        if public_user is None or not _may_sign_in_here(public_user):
            User().set_password(password)
            return None, None
        authenticated = authenticate(
            request,
            email=public_user.email,
            password=password,
        )
        if authenticated is None:
            return public_user, None
        return public_user, authenticated


def login_staff(request, user: User) -> None:
    """Start a session. A public overseer is not written into the child."""
    public = get_public_schema_name()
    home = getattr(user, "_staff_schema", connection.schema_name)
    if home == public and connection.schema_name != public:
        original_save = user.save

        def save_on_public(*args, **kwargs):
            with schema_context(public):
                return original_save(*args, **kwargs)

        user.save = save_on_public  # type: ignore[method-assign]
        try:
            login(request, user)
        finally:
            user.save = original_save  # type: ignore[method-assign]
        request.session[STAFF_HOME_SESSION_KEY] = public
        return
    login(request, user)
    request.session.pop(STAFF_HOME_SESSION_KEY, None)
