from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class UsersConfig(AppConfig):
    name = "break_instantiation_backend.users"
    verbose_name = _("Users")

    def ready(self):
        # Admin autodiscover has already registered tenant models. This app
        # is installed after django.contrib.admin, so this is late enough.
        from break_instantiation_backend.children.admin import (  # noqa: PLC0415
            hide_tenant_models_on_public,
        )

        hide_tenant_models_on_public()
