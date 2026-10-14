from uuid import uuid4

from django.db.models import PROTECT
from django.db.models import BooleanField
from django.db.models import CharField
from django.db.models import CheckConstraint
from django.db.models import DateTimeField
from django.db.models import FloatField
from django.db.models import ForeignKey
from django.db.models import IntegerField
from django.db.models import ManyToManyField
from django.db.models import Model
from django.db.models import OneToOneField
from django.db.models import PositiveIntegerField
from django.db.models import Q
from django.db.models import TextChoices
from django.db.models import TextField
from django.db.models import UniqueConstraint
from django.db.models import UUIDField
from django.utils.translation import gettext_lazy as _
from model_utils.fields import AutoCreatedField
from model_utils.models import TimeStampedModel


class AnswerTypeChoices(TextChoices):
    SINGLE_CHOICE = "single_choice", _("Single choice")
    MULTI_CHOICE = "multi_choice", _("Multi choice")
    FREE_TEXT = "free_text", _("Free text")
    SCALE = "scale", _("Scale")


# The answer types whose answers select `QuestionOption`s, and therefore
# the only ones a per-option `Edge` guard can ever match on -- see
# `routing.selected_option_ids`, which returns nothing for the others.
# Named here rather than in either caller because `diagnostics` uses it to
# report per-option edges that can never fire and `editing` uses it to
# refuse new ones, and those two must not be able to disagree about which
# types count.
CHOICE_ANSWER_TYPES = frozenset(
    {AnswerTypeChoices.SINGLE_CHOICE, AnswerTypeChoices.MULTI_CHOICE},
)


class AssessmentStatus(TextChoices):
    NOT_STARTED = "not_started", _("Not started")
    IN_PROGRESS = "in_progress", _("In progress")
    COMPLETED = "completed", _("Completed")
    EXPIRED = "expired", _("Expired")
    FLAGGED = "flagged", _("Flagged")
    REVIEWED = "reviewed", _("Reviewed")


class RoutingModel(TextChoices):
    """Which resolver decides "what comes next" for a `QuestionnaireVersion`.

    `GRAPH` is the routing model for every product bvi actually walks a
    respondent through itself: every transition is an explicit `Edge` row
    and `display_order` is presentational only. There is no implicit
    fall-through -- if no edge matches, the flow ends.

    The original positional runtime (`SEQUENCE`: every question in
    `display_order`, minus any removed by a `QuestionRule`) retired once
    its last mid-walk assessment finished, and was deleted along with
    `QuestionRule` itself. This is still a `choices`-constrained field
    rather than a bare constant, the same "holds the position" role
    `Questionnaire.is_default` plays -- a second resolver is not expected,
    but nothing here forecloses it.

    `EXTERNAL` is legacy, not a live second resolver: it marked a
    "shadow" version whose real `Section`/`Question`/`Option`/`Edge`
    content lived entirely on break-backend, with nothing local to walk
    or edit -- the write-proxy design BREAK integration used before
    BREAK_LOCAL_CONTENT_INTEGRATION_PLAN.md. That pivot means
    `editing.create_draft_from_break` now copies BREAK's content into
    real local rows and produces an ordinary `GRAPH` version like any
    other product's, so nothing creates an `EXTERNAL` row any more. The
    value stays defined -- and a few read paths (`FlowToolGraphView`,
    `FlowToolVersionListView`'s question-count patch) still special-case
    it -- only so whatever historical rows already carry it keep
    rendering correctly; it is not something new code should branch on.
    """

    GRAPH = "graph", _("Graph")
    EXTERNAL = "external", _("External (shadow version, no local content)")


class Questionnaire(TimeStampedModel):
    """One questionnaire product: the family a `QuestionnaireVersion` belongs to.

    Versions were a flat table until this row existed, and "the
    questionnaire" was whatever string sat in their `name`. That was
    enough while exactly one questionnaire could ever be live, and it is
    what made the singleton constraints on `QuestionnaireVersion`
    tractable -- but it left nothing to hang a second questionnaire off,
    and nothing to scope "the active version" to.

    This is that anchor, and it is deliberately thin: a name, a code, a
    default flag and a note of what it was spawned from. Everything that
    makes a questionnaire what it *is* --
    sections, questions, options, edges -- already hangs off a version,
    so a product is fully described by its versions plus this row. That
    is what keeps standing up another one a matter of copying data rather
    than changing code.

    `is_default` is the interim answer to "which questionnaire does a
    client get". Today there is one questionnaire and the question is not
    interesting; when there are several, the rule that picks between them
    belongs to whatever assigns clients to products, and this flag is
    what that rule replaces. It is not a synonym for `is_active` on a
    version: this says which product is served, that says which revision
    of it.
    """

    id = UUIDField(primary_key=True, default=uuid4, editable=False)
    name = CharField(_("name"), max_length=255)
    # Stable, human-writable handle, unlike `name`, which is prose that
    # gets rewritten. Anything outside the database that has to name a
    # questionnaire -- a seed invocation, an import bundle, a support
    # ticket -- names it by this.
    code = CharField(_("code"), max_length=64, unique=True)
    is_default = BooleanField(_("is default"), default=False)
    # Which version of which product this one was spawned from, and null
    # for a product that was seeded rather than copied. A real FK, unlike
    # the audit trail's plain-UUID columns, because it can only ever point
    # at a *published* version and nothing in the system deletes those --
    # `editing.discard_draft`, the one hard delete here, refuses anything
    # that is not a draft. `PROTECT` then states the consequence: a
    # version with descendants is part of their history and cannot be
    # removed out from under them.
    #
    # Lineage deliberately does not ride on the spawned version's
    # `parent_version`. That column means "the same-questionnaire version
    # this draft was copied from", and `editing.publish` reads it to
    # refuse a draft whose parent is no longer live; pointing it at
    # another product's version would leave one column carrying two
    # meanings, one of which is load-bearing for what may go live.
    spawned_from_version = ForeignKey(
        "QuestionnaireVersion",
        on_delete=PROTECT,
        null=True,
        blank=True,
        related_name="spawned_questionnaires",
    )
    # Soft delete -- the same shape as `Question.archived_at`, and for
    # the same reason: a product can never actually be hard-deleted.
    # Every version under it, and any `flow_tool.ChangeRequest`/
    # `audit.QuestionnaireActivityEvent` that ever touched one, points
    # back at it with `PROTECT`, on purpose (see those models). Archiving
    # is the only removal the Django admin offers -- it drops the product
    # out of `FlowToolProductListView` without touching any of that
    # history, and is reversible by clearing the field again.
    archived_at = DateTimeField(_("archived at"), null=True, blank=True)

    class Meta:
        constraints = [
            UniqueConstraint(
                fields=["is_default"],
                condition=Q(is_default=True),
                name="questionnaire_only_one_default",
            ),
        ]

    def __str__(self) -> str:
        return str(self.name)


class QuestionnaireVersion(TimeStampedModel):
    """A seeded, versioned set of questions a `Client` can be assessed against.

    A version is also the unit of change control. `is_draft` marks a
    version being edited; `is_active` marks the one being served. Editing
    a draft cannot affect a respondent, because
    `services.start_assessment` resolves `is_active=True` and nothing
    else ever reads a non-active version -- so the isolation is a
    property of the schema, not of anyone remembering to be careful.

    That also makes a version its own snapshot: publishing activates the
    draft and leaves the previous version intact, so "undo" is
    "reactivate", and no separate snapshot table is needed.

    Drafts are unlimited, and used to be capped at one by a
    `qv_only_one_draft` partial index. That index was removed rather than
    rescoped: it was doing two jobs, and only one of them was real.
    Single-writer safety is the `ChangeRequest` lock, which is per
    proposal and always was. What the index additionally prevented was
    two proposals diverging from the same parent, where publishing the
    second would silently discard the first -- a version being a whole
    snapshot rather than a diff. That is now refused at the moment it
    would do harm, by `editing.publish`, which declines a draft whose
    `parent_version` is no longer what is active. Forbidding the second
    draft was a way of never reaching that collision, at the cost of
    never letting two people explore two ideas at once.
    """

    id = UUIDField(primary_key=True, default=uuid4, editable=False)
    questionnaire = ForeignKey(
        Questionnaire,
        on_delete=PROTECT,
        related_name="versions",
    )
    name = CharField(_("name"), max_length=255)
    is_active = BooleanField(_("is active"), default=False)
    is_draft = BooleanField(_("is draft"), default=False)
    # GRAPH is the only choice left (see `RoutingModel`'s docstring) --
    # kept as an explicit default rather than inlined, so a version
    # created without specifying one still reads as a deliberate choice.
    routing_model = CharField(
        _("routing model"),
        max_length=16,
        choices=RoutingModel,
        default=RoutingModel.GRAPH,
    )
    # The version's place in its own product's timeline: 1, 2, 3 within
    # this questionnaire, restarting at 1 in a product spawned from it.
    # Nullable, and null for every version that predates the column, the
    # same null a seeded version's `published_at` already carries --
    # numbering runs forward rather than being invented for history.
    #
    # Stamped in exactly two places: `editing.publish`, one past the
    # product's highest, and `editing.spawn_product`, always 1. Not in
    # `services.activate_version`, which is also how a rollback goes live:
    # this is the version's identity, not a statement about which version
    # is being served, so after a rollback the active version is
    # legitimately not the highest-numbered one.
    number = PositiveIntegerField(_("number"), null=True, blank=True)
    parent_version = ForeignKey(
        "self",
        on_delete=PROTECT,
        null=True,
        blank=True,
        related_name="derived_versions",
    )

    class Meta:
        constraints = [
            # Scoped to the questionnaire, not the table: "one live
            # version" is a fact about a product, and two products being
            # live at once is the entire point of there being two.
            UniqueConstraint(
                fields=["questionnaire", "is_active"],
                condition=Q(is_active=True),
                name="qv_only_one_active",
            ),
            CheckConstraint(
                condition=~(Q(is_active=True) & Q(is_draft=True)),
                name="qv_draft_is_not_active",
            ),
            # Per questionnaire, because a number means nothing outside
            # the timeline it counts along: v2 of one product and v2 of a
            # product spawned from it are different questionnaires that
            # have both been published twice. Conditional so that the
            # unnumbered history predating the column does not collide
            # with itself.
            UniqueConstraint(
                fields=["questionnaire", "number"],
                condition=Q(number__isnull=False),
                name="qv_number_unique_per_questionnaire",
            ),
        ]

    def __str__(self) -> str:
        return str(self.name)


class Section(TimeStampedModel):
    """A named group of questions within a `QuestionnaireVersion`.

    Presentational: sections carry the questionnaire's own headings and
    intro copy, and give the editing tool the one fact it colours nodes
    by. Nothing about routing consults them.

    `display_order` deliberately has no unique constraint, unlike
    `Question.display_order`. Uniqueness on an ordering column is exactly
    what makes reordering impossible -- renumbering a run of rows trips
    the constraint mid-statement on PostgreSQL, because it is checked per
    row rather than at statement end. Ties break on `code` so ordering
    stays deterministic regardless.
    """

    id = UUIDField(primary_key=True, default=uuid4, editable=False)
    questionnaire_version = ForeignKey(
        QuestionnaireVersion,
        on_delete=PROTECT,
        related_name="sections",
    )
    code = CharField(_("code"), max_length=64)
    name = CharField(_("name"), max_length=255)
    description = TextField(_("description"), blank=True, default="")
    display_order = IntegerField(_("display order"))

    class Meta:
        constraints = [
            UniqueConstraint(
                fields=["questionnaire_version", "code"],
                name="questionnaires_section_version_code_unique",
            ),
        ]
        ordering = ["questionnaire_version", "display_order", "code"]

    def __str__(self) -> str:
        return f"{self.code}: {self.name}"


class Question(TimeStampedModel):
    """A single question belonging to a `QuestionnaireVersion`.

    No scoring metadata (category, BPM dimension, weight) -- that belongs
    to a separate, not-yet-designed scoring piece and would only join
    against `id`.
    """

    id = UUIDField(primary_key=True, default=uuid4, editable=False)
    questionnaire_version = ForeignKey(
        QuestionnaireVersion,
        on_delete=PROTECT,
        related_name="questions",
    )
    code = CharField(_("code"), max_length=64)
    prompt = TextField(_("prompt"))
    # Supporting copy shown between the prompt and the options/visual --
    # e.g. the explanatory paragraph a risk-tolerance question hangs its
    # answer choices off of. Kept separate from `prompt` so anything that
    # renders the prompt alone (progress summaries, flow-tool node labels)
    # doesn't have to reformat or truncate a mixed blob.
    subtext = TextField(_("subtext"), blank=True, default="")
    # Presentation-only grouping within a section, for batching several
    # questions onto one screen instead of one at a time (see
    # `routing.unconditional_run`, `services.BATCH_PRESENTATION_SECTION_
    # CODES`) -- not the scoring-category metadata the class docstring
    # above rules out. It happens to hold the timeline content's own
    # category label (`timeline_number` in `timeline_questions_final.csv`,
    # e.g. "1+ Chaos") because that was already the natural grouping key,
    # not because this field means anything to a future scoring model.
    # Blank for every question outside a batched section.
    batch_group = CharField(_("batch group"), max_length=32, blank=True, default="")
    answer_type = CharField(
        _("answer type"),
        max_length=32,
        choices=AnswerTypeChoices,
    )
    is_required = BooleanField(_("is required"), default=True)
    # Presentational under `RoutingModel.GRAPH`, with one exception -- the
    # lowest-ordered live question is the entry point, since there is no
    # separate entry marker.
    display_order = IntegerField(_("display order"))
    show_raw_answer_to_advisor = BooleanField(
        _("show raw answer to advisor"),
        default=False,
    )
    section = ForeignKey(
        Section,
        on_delete=PROTECT,
        null=True,
        blank=True,
        related_name="questions",
    )
    # Soft delete. Hard deletion is already impossible once a question has
    # been answered (`Answer.question` is PROTECT), and historical answers
    # have to stay readable, so removal from the active flow is the only
    # kind of deletion there is.
    archived_at = DateTimeField(_("archived at"), null=True, blank=True)
    # break-backend's own `Question.routing_protected` concept, meaningless
    # for every non-BREAK product -- production's diagnostic hardcodes a
    # phase transition through this specific question regardless of what
    # its own routing says (see BREAK_ROUTING_REFACTOR_PLAN.md). Preserved
    # here purely so a BREAK-hosted draft's copy-in/push-out round trip
    # (`editing.create_draft_from_break`/`submit`) doesn't silently drop it
    # -- losing this flag on a real publish would desync bvi's local edit
    # from what break's production code actually does at that question,
    # not just from what bvi's own routing thinks happens. `editing.py`'s
    # local guards (archive/delete refusal) do not yet enforce anything off
    # this field -- see BREAK_LOCAL_CONTENT_INTEGRATION_PLAN.md's open
    # question on that; break's own `validate_no_routing_cycle` still
    # catches an unreachable protected question at submit/publish either
    # way, so the round trip stays correct without it.
    routing_protected = BooleanField(_("routing protected"), default=False)

    class Meta:
        constraints = [
            UniqueConstraint(
                fields=["questionnaire_version", "code"],
                name="questionnaires_question_version_code_unique",
            ),
            UniqueConstraint(
                fields=["questionnaire_version", "display_order"],
                name="questionnaires_question_version_order_unique",
            ),
        ]
        ordering = ["questionnaire_version", "display_order"]

    def __str__(self) -> str:
        return f"{self.code}: {self.prompt[:50]}"


class QuestionOption(Model):
    """A selectable choice for a `single_choice`/`multi_choice` `Question`.

    Rows are seeded once, never edited, so there is no `modified` column
    (no `TimeStampedModel`), matching `users.Permission`.
    """

    id = UUIDField(primary_key=True, default=uuid4, editable=False)
    question = ForeignKey(Question, on_delete=PROTECT, related_name="options")
    code = CharField(_("code"), max_length=64)
    label = TextField(_("label"))
    display_order = IntegerField(_("display order"))
    created = AutoCreatedField(_("created"))

    class Meta:
        constraints = [
            UniqueConstraint(
                fields=["question", "code"],
                name="questionnaires_questionoption_question_code_unique",
            ),
            UniqueConstraint(
                fields=["question", "display_order"],
                name="questionnaires_questionoption_question_order_unique",
            ),
        ]
        ordering = ["question", "display_order"]

    def __str__(self) -> str:
        return f"{self.question.code}: {self.label}"


class Edge(TimeStampedModel):
    """One explicit transition out of a question, for `RoutingModel.GRAPH`.

    The entire graph runtime is: take the edges leaving this question in
    `priority` order and return the first whose guard matches. There is no
    implicit fall-through and no positional rule -- if nothing matches,
    the flow ends.

    `from_option` NULL is the question-level edge: it matches any answer,
    and is how a question that does not branch per answer (free text,
    scale, and any choice question whose answers all lead to the same
    place) states its single destination. Give it a higher `priority`
    number than the per-answer edges so it acts as the fallback.

    `to_question` NULL means the flow ends here. This does *not* need a
    separate ends-flow flag: the ambiguity that flag exists to resolve --
    "no rule" versus "stop" both reading as NULL -- cannot arise when the
    edge is its own row, because "no rule" is the absence of a row.

    Two things a database cannot check and a service therefore must:
    `from_option` genuinely belonging to `from_question`, and both
    questions belonging to the same version. A mismatched `from_option`
    is inert rather than wrong (it can never match an answer to a
    different question), but a cross-version `to_question` is not, and
    `resolve` rejects it loudly.
    """

    id = UUIDField(primary_key=True, default=uuid4, editable=False)
    from_question = ForeignKey(
        Question,
        on_delete=PROTECT,
        related_name="outgoing_edges",
    )
    from_option = ForeignKey(
        QuestionOption,
        on_delete=PROTECT,
        null=True,
        blank=True,
        related_name="outgoing_edges",
    )
    to_question = ForeignKey(
        Question,
        on_delete=PROTECT,
        null=True,
        blank=True,
        related_name="incoming_edges",
    )
    priority = IntegerField(_("priority"))

    class Meta:
        constraints = [
            UniqueConstraint(
                fields=["from_question", "priority"],
                name="questionnaires_edge_question_priority_unique",
            ),
            # Two partial constraints rather than one over
            # (from_question, from_option), because PostgreSQL treats
            # NULLs as distinct in a unique index -- a plain constraint
            # would happily allow a question two question-level edges,
            # which is an unresolvable tie.
            UniqueConstraint(
                fields=["from_question", "from_option"],
                condition=Q(from_option__isnull=False),
                name="questionnaires_edge_one_per_option",
            ),
            UniqueConstraint(
                fields=["from_question"],
                condition=Q(from_option__isnull=True),
                name="questionnaires_edge_one_fallback_per_question",
            ),
        ]
        ordering = ["from_question", "priority"]

    def __str__(self) -> str:
        source = self.from_question.code
        via = self.from_option.code if self.from_option else "any answer"
        target = self.to_question.code if self.to_question else "END"
        return f"{source} [{via}] -> {target}"


class Assessment(TimeStampedModel):
    """A `Client`'s single attempt at a `QuestionnaireVersion`.

    The table every downstream piece (reports, scoring, notifications,
    audit) is expected to key off -- never `QuestionnaireSession`.
    `UNIQUE(client)` is a deliberate one-assessment-per-client boundary for
    this pass, not an oversight; reassessment is a separate, later design.
    """

    id = UUIDField(primary_key=True, default=uuid4, editable=False)
    client = OneToOneField(
        "clients.Client",
        on_delete=PROTECT,
        related_name="assessment",
    )
    questionnaire_version = ForeignKey(
        QuestionnaireVersion,
        on_delete=PROTECT,
        related_name="assessments",
    )
    status = CharField(
        _("status"),
        max_length=16,
        choices=AssessmentStatus,
        default=AssessmentStatus.NOT_STARTED,
    )
    started_at = DateTimeField(_("started at"), null=True, blank=True)
    completed_at = DateTimeField(_("completed at"), null=True, blank=True)

    def __str__(self) -> str:
        return f"{self.client} ({self.status})"


class QuestionnaireSession(Model):
    """The live walk-through state for an `Assessment`.

    Not a `TimeStampedModel`: `last_activity_at` is hand-updated by the
    answer-submission service on every request, distinct from a generic
    `modified` side effect. No `expires_at`/expiry logic -- `ClientSession`
    idle timeout already bounds how long a stalled session matters; see
    spec. No stored progress field -- the adaptive-branching denominator is
    dynamic per-client and is computed at read-time instead.
    """

    id = UUIDField(primary_key=True, default=uuid4, editable=False)
    assessment = OneToOneField(
        Assessment,
        on_delete=PROTECT,
        related_name="session",
    )
    current_question = ForeignKey(
        Question,
        on_delete=PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )
    started_at = DateTimeField(_("started at"), null=True, blank=True)
    completed_at = DateTimeField(_("completed at"), null=True, blank=True)
    last_activity_at = DateTimeField(_("last activity at"))

    def __str__(self) -> str:
        return f"Session for {self.assessment}"


class Answer(TimeStampedModel):
    """A `Client`'s recorded answer to one `Question` within a `QuestionnaireSession`.

    Create-only and immutable: `UNIQUE(session, question)` is the backstop
    against a duplicate write if the service layer's current-question guard
    is ever bypassed by a bug or a race -- it turns that bypass into a loud
    `IntegrityError` rather than a silent overwrite (see spec, "Required-
    question handling"). Type-integrity is two-tier (see spec, Decision 5):
    the `answer_at_most_one_scalar_field` CHECK below is the DB-level
    guarantee that survives a bypass of app-layer validation, though it
    only covers the scalar-field collision case, not the full answer_type
    match (the app layer, built in Phase 3, owns that).
    """

    id = UUIDField(primary_key=True, default=uuid4, editable=False)
    session = ForeignKey(
        QuestionnaireSession,
        on_delete=PROTECT,
        related_name="answers",
    )
    question = ForeignKey(Question, on_delete=PROTECT, related_name="answers")
    selected_option = ForeignKey(
        QuestionOption,
        on_delete=PROTECT,
        null=True,
        blank=True,
        related_name="selected_by_answers",
    )
    selected_options = ManyToManyField(
        QuestionOption,
        blank=True,
        related_name="multi_selected_by_answers",
    )
    free_text_value = TextField(_("free text value"), null=True, blank=True)  # noqa: DJ001
    scale_value = IntegerField(_("scale value"), null=True, blank=True)
    answered_at = DateTimeField(_("answered at"), null=True, blank=True)
    # Wall-clock time between this question being presented and this answer
    # being submitted -- see `services.submit_answer`, which derives it from
    # `session.last_activity_at` (the previous answer's `answered_at`, or
    # `session.started_at` for the first question) read *before* that field
    # is overwritten for this submission. Stored per-row rather than
    # recomputed from timestamp gaps on every read: this is the shape a
    # future scoring model consumes (per-question, not per-assessment), so
    # it belongs on the row it describes, not buried in an audit log.
    seconds_taken = FloatField(_("seconds taken"), null=True, blank=True)

    class Meta:
        constraints = [
            UniqueConstraint(
                fields=["session", "question"],
                name="questionnaires_answer_session_question_unique",
            ),
            CheckConstraint(
                condition=(
                    Q(
                        selected_option__isnull=True,
                        free_text_value__isnull=True,
                        scale_value__isnull=True,
                    )
                    | Q(
                        selected_option__isnull=False,
                        free_text_value__isnull=True,
                        scale_value__isnull=True,
                    )
                    | Q(
                        selected_option__isnull=True,
                        free_text_value__isnull=False,
                        scale_value__isnull=True,
                    )
                    | Q(
                        selected_option__isnull=True,
                        free_text_value__isnull=True,
                        scale_value__isnull=False,
                    )
                ),
                name="answer_at_most_one_scalar_field",
            ),
        ]

    def __str__(self) -> str:
        return f"Answer to {self.question.code} in {self.session_id}"


class ConsentTemplate(Model):
    """A named, versioned snapshot of the consent/privacy-policy text a
    client is shown before granting questionnaire consent.

    Stores the actual `text`, not just a version label the frontend
    resolves separately -- a compliance reviewer needs to reconstruct
    exactly what a specific client agreed to on demand, without depending
    on the frontend/CMS still having that old wording around. Same
    `is_active` versioning pattern as `QuestionnaireVersion`/
    `TrustSignalRankingVersion`: exactly one active at a time (partial
    unique constraint below), activated via
    `services.activate_consent_template`, not a code change.

    Immutable once created (`save()` below) -- a wording fix publishes a
    new version rather than editing this one, so a `ConsentRecord.template`
    reference never points at text that could have silently changed after
    the fact. `is_active` is the one field allowed to change afterward
    (that's what activation *is*).
    """

    id = UUIDField(primary_key=True, default=uuid4, editable=False)
    version = CharField(_("version"), max_length=16, unique=True)
    text = TextField(_("text"))
    is_active = BooleanField(_("is active"), default=False)
    created = AutoCreatedField(_("created"))

    class Meta:
        constraints = [
            UniqueConstraint(
                fields=["is_active"],
                condition=Q(is_active=True),
                name="consent_template_only_one_active",
            ),
        ]

    def __str__(self) -> str:
        return str(self.version)

    def save(self, *args, **kwargs):
        if not self._state.adding:
            # Compares actual values, not `update_fields` -- a full-form
            # save (Django admin's default, no `update_fields` passed)
            # must still be allowed as long as `version`/`text` didn't
            # actually change, e.g. toggling `is_active` there.
            current = ConsentTemplate.objects.get(pk=self.pk)
            if current.version != self.version or current.text != self.text:
                msg = (
                    "ConsentTemplate.version/text are immutable once "
                    "created -- publish a new version instead of editing "
                    "this one."
                )
                raise ValueError(msg)
        super().save(*args, **kwargs)


class ConsentRecord(Model):
    """A `Client`'s grant of questionnaire consent -- currently at most
    one per client (`UNIQUE(client)`), representing their *current*
    consent status, not a full history of every grant/withdrawal
    (deliberate scope, see `OPEN_QUESTIONS.md`; the append-only audit
    trail for the history itself is
    `audit.AssessmentActivityEvent.CONSENT_GRANTED`/`CONSENT_WITHDRAWN`,
    same "current state here, history there" split as `ClientUser.
    disabled_at` + `ClientActivityEvent.PORTAL_ACCESS_DISABLED`/`_ENABLED`).

    `template` is nullable -- rows created before `ConsentTemplate`
    existed have no version to point at; that gap is a known, honest
    one, not backfilled with a guess. `withdrawn_at` mirrors
    `ClientUser.disabled_at`: `None` means currently consented,
    `services.withdraw_consent`/`grant_consent` are the only writers.
    `UNIQUE(client)` is what makes `services.grant_consent`'s
    `get_or_create` actually race-safe -- without it, two concurrent
    requests can both miss the `get()` and both `create()`.
    """

    id = UUIDField(primary_key=True, default=uuid4, editable=False)
    client = OneToOneField(
        "clients.Client",
        on_delete=PROTECT,
        related_name="consent_record",
    )
    template = ForeignKey(
        ConsentTemplate,
        on_delete=PROTECT,
        null=True,
        blank=True,
        related_name="consent_records",
    )
    withdrawn_at = DateTimeField(_("withdrawn at"), null=True, blank=True)
    created_at = AutoCreatedField(_("created at"))

    def __str__(self) -> str:
        return f"Consent for {self.client}"
