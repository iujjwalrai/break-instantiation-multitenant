from django.urls import path

from .staff_views import StaffAdminListCreateView
from .staff_views import StaffLoginView
from .staff_views import StaffLogoutView
from .staff_views import StaffMeView

app_name = "staff"
urlpatterns = [
    path("login/", StaffLoginView.as_view(), name="login"),
    path("logout/", StaffLogoutView.as_view(), name="logout"),
    path("me/", StaffMeView.as_view(), name="me"),
    path("admins/", StaffAdminListCreateView.as_view(), name="admins"),
]
