from django.urls import path

from .views import AssessmentAnswerBatchView
from .views import AssessmentStartView
from .views import ConsentGrantView
from .views import ConsentTemplateView

app_name = "assessment"
urlpatterns = [
    path("consent/template/", ConsentTemplateView.as_view(), name="consent-template"),
    path("consent/", ConsentGrantView.as_view(), name="consent"),
    path("start/", AssessmentStartView.as_view(), name="start"),
    path("answers/", AssessmentAnswerBatchView.as_view(), name="answers"),
]
