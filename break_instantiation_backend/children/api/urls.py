from django.urls import path

from .views import LookView

app_name = "children"
urlpatterns = [
    path("look/", LookView.as_view(), name="look"),
]
