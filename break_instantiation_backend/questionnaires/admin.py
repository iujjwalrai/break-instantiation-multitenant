from functools import reduce
from typing import Any
from typing import ClassVar

from django.contrib import admin
from django.contrib import messages
from django.db.models import Q
from django.utils import timezone

from .models import Answer
from .models import Assessment
from .models import ConsentRecord
from .models import ConsentTemplate
from .models import Edge
from .models import Question
from .models import Questionnaire
from .models import QuestionnaireSession
from .models import QuestionnaireVersion
from .models import QuestionOption
from .models import Section
from .routing import RoutingError
from .services import activate_consent_template
from .services import activate_version

PROMPT_PREVIEW_LENGTH = 80


class ReadOnlyAdminMixin:
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class NoDeleteAdminMixin:
    def has_delete_permission(self, request, obj=None):
        return False


class QuestionOptionInline(admin.TabularInline):
    model = QuestionOption
    extra = 0

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Questionnaire)
class QuestionnaireAdmin(NoDeleteAdminMixin, admin.ModelAdmin):
    """A product can be created here. The flow tool is not part of this
    deployment, so this admin is how the one questionnaire is stood up.
    Archiving hides it without deleting versions that answers point at.
    """

    list_display = ["code", "name", "is_default", "archived_at", "created"]
    list_filter = ["is_default", "archived_at"]
    search_fields = ["code", "name"]
    actions = ["archive_products", "unarchive_products"]

    @admin.action(description="Archive selected products (hide from the product list)")
    def archive_products(self, request, queryset):
        blocked = queryset.filter(is_default=True)
        if blocked.exists():
            names = ", ".join(blocked.values_list("name", flat=True))
            self.message_user(
                request,
                f"Skipped {names}: the default product can't be archived.",
                level=messages.ERROR,
            )
        updated = (
            queryset.exclude(is_default=True)
            .filter(archived_at__isnull=True)
            .update(archived_at=timezone.now())
        )
        if updated:
            self.message_user(request, f"Archived {updated} product(s).")

    @admin.action(description="Unarchive selected products")
    def unarchive_products(self, request, queryset):
        updated = queryset.filter(archived_at__isnull=False).update(archived_at=None)
        if updated:
            self.message_user(request, f"Unarchived {updated} product(s).")


@admin.register(QuestionnaireVersion)
class QuestionnaireVersionAdmin(NoDeleteAdminMixin, admin.ModelAdmin):
    list_display = [
        "name",
        "questionnaire",
        "number",
        "is_active",
        "is_draft",
        "created",
        "modified",
    ]
    list_filter = ["questionnaire", "is_active", "is_draft"]
    search_fields = ["name"]
    actions = ["activate_versions"]

    @admin.action(description="Activate the selected version")
    def activate_versions(self, request, queryset):
        if queryset.count() != 1:
            self.message_user(
                request,
                "Select exactly one version to activate.",
                level=messages.ERROR,
            )
            return
        version = queryset.get()
        try:
            activate_version(version)
        except RoutingError as exc:
            self.message_user(request, str(exc), level=messages.ERROR)
            return
        self.message_user(request, f"{version.name} is now the live version.")


class LiveVersionFilter(admin.SimpleListFilter):
    """Defaults to each unarchived product's live and draft versions.

    "All versions" opts out.
    """

    title = "version scope"
    parameter_name = "scope"

    def __init__(self, request, params, model, model_admin):
        super().__init__(request, params, model, model_admin)
        # Each admin names the path from its model to its QuestionnaireVersion.
        self.version_path = model_admin.version_path

    def lookups(self, request, model_admin):
        return [("all", "All versions")]

    def queryset(self, request, queryset):
        if self.value() == "all":
            return queryset
        return queryset.filter(
            Q(**{f"{self.version_path}__is_active": True})
            | Q(**{f"{self.version_path}__is_draft": True}),
            **{f"{self.version_path}__questionnaire__archived_at__isnull": True},
        )

    def choices(self, changelist):
        yield {
            "selected": self.value() is None,
            "query_string": changelist.get_query_string(remove=[self.parameter_name]),
            "display": "Live & draft versions",
        }
        for lookup, title in self.lookup_choices:
            yield {
                "selected": self.value() == str(lookup),
                "query_string": changelist.get_query_string(
                    {self.parameter_name: lookup},
                ),
                "display": title,
            }


class VersionScopedAdminMixin:
    """Scopes an admin to live versions and adds a Product column and filters.

    A subclass sets `version_path`, the ORM path from its model to
    `QuestionnaireVersion`, and lists "product" in `list_display`. Any
    `list_filter` / `list_select_related` it declares are appended to the
    ones built here.
    """

    version_path: str
    # Assigned per subclass in `__init_subclass__`.
    list_filter: ClassVar[Any]
    list_select_related: ClassVar[Any]
    product: ClassVar[Any]

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        path = cls.version_path
        cls.list_filter = [
            LiveVersionFilter,
            f"{path}__questionnaire",
            path,
            *cls.__dict__.get("list_filter", ()),
        ]
        cls.list_select_related = [
            f"{path}__questionnaire",
            *cls.__dict__.get("list_select_related", ()),
        ]

        def product(self, obj):
            return reduce(getattr, path.split("__"), obj).questionnaire

        cls.product = admin.display(
            description="Product",
            ordering=f"{path}__questionnaire__name",
        )(product)


PRODUCT_ORDERING: Any = [
    "questionnaire_version__questionnaire__name",
    "display_order",
    "code",
]


@admin.register(Section)
class SectionAdmin(VersionScopedAdminMixin, NoDeleteAdminMixin, admin.ModelAdmin):
    version_path = "questionnaire_version"
    list_display = ["code", "name", "product", "questionnaire_version", "display_order"]
    ordering = PRODUCT_ORDERING
    search_fields = ["code", "name"]


@admin.register(Question)
class QuestionAdmin(VersionScopedAdminMixin, NoDeleteAdminMixin, admin.ModelAdmin):
    version_path = "questionnaire_version"
    list_display = [
        "code",
        "product",
        "questionnaire_version",
        "prompt_preview",
        "answer_type",
        "display_order",
        "is_required",
        "archived_at",
    ]
    list_filter = ["answer_type", "archived_at"]
    ordering = PRODUCT_ORDERING
    search_fields = ["code", "prompt"]
    inlines = [QuestionOptionInline]

    @admin.display(description="Prompt")
    def prompt_preview(self, obj):
        if len(obj.prompt) <= PROMPT_PREVIEW_LENGTH:
            return obj.prompt
        return obj.prompt[:PROMPT_PREVIEW_LENGTH] + "…"


@admin.register(QuestionOption)
class QuestionOptionAdmin(
    VersionScopedAdminMixin,
    NoDeleteAdminMixin,
    admin.ModelAdmin,
):
    version_path = "question__questionnaire_version"
    list_display = ["question", "product", "code", "display_order"]
    search_fields = ["code", "label"]


@admin.register(Edge)
class EdgeAdmin(VersionScopedAdminMixin, NoDeleteAdminMixin, admin.ModelAdmin):
    version_path = "from_question__questionnaire_version"
    list_display = [
        "from_question",
        "product",
        "from_option",
        "to_question",
        "priority",
    ]
    list_select_related = ["from_option", "to_question"]
    search_fields = ["from_question__code", "to_question__code"]


@admin.register(Assessment)
class AssessmentAdmin(ReadOnlyAdminMixin, admin.ModelAdmin):
    list_display = [
        "client",
        "questionnaire_version",
        "status",
        "started_at",
        "completed_at",
    ]
    list_filter = ["status", "questionnaire_version"]
    search_fields = ["client__full_name", "client__email"]


@admin.register(QuestionnaireSession)
class QuestionnaireSessionAdmin(ReadOnlyAdminMixin, admin.ModelAdmin):
    list_display = ["assessment", "current_question", "started_at", "last_activity_at"]
    search_fields = ["assessment__client__full_name", "assessment__client__email"]


@admin.register(Answer)
class AnswerAdmin(ReadOnlyAdminMixin, admin.ModelAdmin):
    list_display = ["session", "question", "answered_at", "seconds_taken", "modified"]
    list_filter = ["question__questionnaire_version"]
    search_fields = ["question__code"]


@admin.register(ConsentRecord)
class ConsentRecordAdmin(ReadOnlyAdminMixin, admin.ModelAdmin):
    list_display = ["client", "template", "withdrawn_at", "created_at"]
    list_filter = ["withdrawn_at"]
    search_fields = ["client__full_name", "client__email"]


@admin.register(ConsentTemplate)
class ConsentTemplateAdmin(admin.ModelAdmin):
    """Unlike every other versioned-content model in this app
    (`QuestionnaireVersion`/`TrustSignalRankingVersion`, both
    `ReadOnlyAdminMixin`), this one allows admin-based creation and
    `is_active` toggling directly -- a single text field is simple
    enough to type into a textarea, no CSV-authoring pipeline needed.
    `version`/`text` are still immutable once created (enforced by the
    model's own `save()`, not just hidden here) --
    `get_readonly_fields` locks them in the form too so that's visible
    rather than a surprise `ValueError` on submit.
    """

    list_display = ["version", "is_active", "created"]
    list_filter = ["is_active"]
    search_fields = ["version"]

    def get_readonly_fields(self, request, obj=None):
        if obj is None:
            return []
        return ["version", "text"]

    def has_delete_permission(self, request, obj=None):
        return False

    def save_model(self, request, obj, form, change):
        should_activate = obj.is_active
        if should_activate:
            obj.is_active = False
        super().save_model(request, obj, form, change)
        if should_activate:
            activate_consent_template(obj)
