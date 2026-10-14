from uuid import uuid4

from django.db.models import PROTECT
from django.db.models import DateTimeField
from django.db.models import ForeignKey
from django.db.models import JSONField
from django.db.models import Model
from django.db.models import OneToOneField
from django.db.models import PositiveSmallIntegerField
from django.db.models import UUIDField
from django.utils.translation import gettext_lazy as _
from model_utils.fields import AutoCreatedField


class AssessmentResult(Model):
    """A score BREAK returned for one completed assessment.

    Written only after a successful scoring call. A failed, refused, or
    unconfigured call leaves this table empty for that assessment. `payload`
    is BREAK's response body. This model does not store an EJ behavior
    pattern or a BVI risk band, and it does not invent either when the
    call fails.

    Keyed by assessment so a later reassessment can have its own row.
    `client` is the same profile the assessment belongs to, stored here so
    a result can be listed without joining through the session.
    """

    id = UUIDField(primary_key=True, default=uuid4, editable=False)
    assessment = OneToOneField(
        "questionnaires.Assessment",
        on_delete=PROTECT,
        related_name="result",
    )
    client = ForeignKey(
        "clients.Client",
        on_delete=PROTECT,
        related_name="assessment_results",
    )
    payload = JSONField(_("BREAK response"))
    http_status = PositiveSmallIntegerField(_("HTTP status"))
    scored_at = DateTimeField(_("scored at"))
    created_at = AutoCreatedField(_("created at"))

    class Meta:
        ordering = ["-scored_at"]

    def __str__(self) -> str:
        return f"Result for {self.assessment_id}"
