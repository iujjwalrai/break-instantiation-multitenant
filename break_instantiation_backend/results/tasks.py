from celery import shared_task
from django_tenants.utils import schema_context

from break_instantiation_backend.children.schema import require_child_schema
from break_instantiation_backend.results.services import score_completed_assessment


@shared_task()
def score_assessment_task(schema_name: str, assessment_id: str) -> None:
    """Score one completed assessment in that child. No row without a child."""
    require_child_schema(schema_name)
    with schema_context(schema_name):
        score_completed_assessment(assessment_id)
