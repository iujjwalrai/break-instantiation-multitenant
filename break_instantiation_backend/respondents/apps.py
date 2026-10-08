from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class RespondentsConfig(AppConfig):
    name = "break_instantiation_backend.respondents"
    verbose_name = _("Respondents")
