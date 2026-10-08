from django.urls import path

from .views import MagicLoginRedeemView
from .views import MagicLoginRequestView
from .views import RespondentLogoutAllView
from .views import RespondentLogoutView

app_name = "respondent_auth"
urlpatterns = [
    path(
        "magic-login/request/",
        MagicLoginRequestView.as_view(),
        name="magic-login-request",
    ),
    path(
        "magic-login/redeem/",
        MagicLoginRedeemView.as_view(),
        name="magic-login-redeem",
    ),
    path("logout/", RespondentLogoutView.as_view(), name="logout"),
    path("logout-all/", RespondentLogoutAllView.as_view(), name="logout-all"),
]
