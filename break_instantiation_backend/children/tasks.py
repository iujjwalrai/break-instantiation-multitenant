from celery import shared_task
from django_tenants.utils import schema_context

from break_instantiation_backend.children.schema import require_child_schema


@shared_task()
def touch_child(schema_name: str) -> str:
    """Enter one child schema. The scheduler refuses a missing child id."""
    require_child_schema(schema_name)
    with schema_context(schema_name):
        return schema_name
