from django.db import connection
from django_tenants.utils import get_public_schema_name
from django_tenants.utils import schema_context

from break_instantiation_backend.children.look import public_look
from break_instantiation_backend.children.models import Child


def require_child_schema(schema_name: str) -> str:
    """Background work names a child and refuses to run without one."""
    if not schema_name or schema_name == get_public_schema_name():
        msg = "Background jobs require a child schema."
        raise RuntimeError(msg)
    return schema_name


def current_child_schema() -> str:
    return require_child_schema(getattr(connection, "schema_name", "") or "")


def current_look() -> dict:
    """Branding for the company this request is already on."""
    schema_name = current_child_schema()
    with schema_context(get_public_schema_name()):
        child = Child.objects.get(schema_name=schema_name)
    return public_look(name=child.name, look=child.look)


def current_client_site() -> str:
    """The customer-app origin stored on this company. Mail uses it as-is."""
    schema_name = current_child_schema()
    with schema_context(get_public_schema_name()):
        url = (
            Child.objects.filter(schema_name=schema_name)
            .values_list("client_site_url", flat=True)
            .first()
        )
    if not url:
        msg = f"{schema_name} has no client site URL."
        raise RuntimeError(msg)
    return url


def enqueue_child_task(task, *args, **kwargs):
    """Queue `task` for the child that is active on this connection."""
    schema_name = current_child_schema()
    return task.delay(schema_name, *args, **kwargs)


def enqueue_for_each_child(task, *args, **kwargs) -> int:
    """Fan a task out once per child. The scheduler loops children this way."""
    public = get_public_schema_name()
    with schema_context(public):
        schemas = list(
            Child.objects.exclude(schema_name=public).values_list(
                "schema_name",
                flat=True,
            ),
        )
    for schema_name in schemas:
        task.delay(schema_name, *args, **kwargs)
    return len(schemas)
