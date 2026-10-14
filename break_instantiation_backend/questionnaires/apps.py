from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class QuestionnairesConfig(AppConfig):
    name = "break_instantiation_backend.questionnaires"
    verbose_name = _("Questionnaires")
