from django.conf import settings
from django.urls import include
from django.urls import path
from rest_framework.routers import DefaultRouter
from rest_framework.routers import SimpleRouter

from break_instantiation_backend.users.api.views import UserViewSet

router = DefaultRouter() if settings.DEBUG else SimpleRouter()

router.register("users", UserViewSet)


app_name = "api"
urlpatterns = [
    path(
        "clients/auth/",
        include("break_instantiation_backend.clients.api.auth.urls"),
    ),
    path("clients/", include("break_instantiation_backend.clients.api.urls")),
    path("staff/", include("break_instantiation_backend.users.api.staff_urls")),
    *router.urls,
]
