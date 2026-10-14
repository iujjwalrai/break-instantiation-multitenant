from django.core.exceptions import ValidationError
from django.db.models import CharField
from django.db.models import JSONField
from django.db.models import TextChoices
from django.db.models import URLField
from django.utils.translation import gettext_lazy as _
from django_tenants.models import DomainMixin
from django_tenants.models import TenantMixin

from break_instantiation_backend.children.look import validate_look


class ChildStatus(TextChoices):
    DRAFT = "draft", _("Draft")
    LIVE = "live", _("Live")


class Child(TenantMixin):
    """One customer on this deployment. The row lives on `public`.

    `schema_name` is the Postgres schema for that child's admins, clients,
    sessions, invites, magic links, consent, questionnaire, results, and
    audit. `domains` is the address that selects this company.     `client_site_url`
    is the customer app. Invite and magic-link mail use that string as the
    link base. `look` is the name, logo, and colors both frontends apply
    at runtime. Report style and scoring route stay empty until a later
    phase fills them in.
    """

    name = CharField(_("name"), max_length=100)
    status = CharField(
        _("status"),
        max_length=16,
        choices=ChildStatus,
        default=ChildStatus.DRAFT,
    )
    look = JSONField(
        _("look"),
        default=dict,
        blank=True,
        help_text=_(
            "Name, logo, and colors for this company. Keys: name, logo, "
            "favicon, title, description, and colors.primary, "
            "colors.primaryForeground, colors.primaryHover. "
            "Example: "
            '{"name": "EJ", "logo": "", "colors": {"primary": "#1B4D3E", '
            '"primaryForeground": "#ffffff", "primaryHover": "#14382D"}}.',
        ),
    )
    report_style = CharField(_("report style"), max_length=64, blank=True, default="")
    scoring_route = CharField(
        _("scoring route"),
        max_length=255,
        blank=True,
        default="",
    )
    client_site_url = URLField(
        _("client site"),
        max_length=255,
        blank=True,
        default="",
        help_text=_(
            "Customer app origin. Invite and magic-link mail use this "
            "string as the link base.",
        ),
    )

    auto_create_schema = True

    def clean(self):
        super().clean()
        errors = validate_look(self.look)
        if errors:
            raise ValidationError({"look": errors})

    class Meta:
        verbose_name = _("Child")
        verbose_name_plural = _("Children")

    def __str__(self) -> str:
        return self.name


class ChildDomain(DomainMixin):
    """What selects a child: a path slug (/t/ej/) or a host (ej.localhost).

    A slug has no dots, so it never matches a host. Unknown values match no row.
    """

    class Meta:
        verbose_name = _("Child path or host")
        verbose_name_plural = _("Child paths and hosts")

    def __str__(self) -> str:
        return self.domain
