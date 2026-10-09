from django.urls import path

from .views import MagicLoginRedeemView
from .views import MagicLoginRequestView
from .views import PortalInviteRedeemView
from .views import PortalInviteVerifyView
from .views import PortalLogoutAllView
from .views import PortalLogoutView

app_name = "client_auth"
urlpatterns = [
    path("invites/verify/", PortalInviteVerifyView.as_view(), name="invite-verify"),
    path("invites/redeem/", PortalInviteRedeemView.as_view(), name="invite-redeem"),
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
    path("logout/", PortalLogoutView.as_view(), name="logout"),
    path("logout-all/", PortalLogoutAllView.as_view(), name="logout-all"),
]
