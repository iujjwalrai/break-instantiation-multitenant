from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class ChildrenConfig(AppConfig):
    name = "break_instantiation_backend.children"
    verbose_name = _("Children")
