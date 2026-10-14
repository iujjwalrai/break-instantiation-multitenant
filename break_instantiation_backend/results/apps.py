from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class ResultsConfig(AppConfig):
    name = "break_instantiation_backend.results"
    verbose_name = _("Results")
