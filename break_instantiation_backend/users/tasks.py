from celery import shared_task
from django_tenants.utils import schema_context

from break_instantiation_backend.children.schema import require_child_schema

from .models import User


@shared_task()
def get_users_count(schema_name: str) -> int:
    """Count users in one child. Refuses to run without that schema."""
    require_child_schema(schema_name)
    with schema_context(schema_name):
        return User.objects.count()
