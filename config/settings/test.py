"""
With these settings, tests run faster.
"""

from .base import *  # noqa: F403
from .base import TEMPLATES
from .base import env

# GENERAL
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#secret-key
SECRET_KEY = env(
    "DJANGO_SECRET_KEY",
    default="DJ94uObmYgbQwuUyljbIUcGLae5MPsaLd2LUlRIq6KBZH6MBvj18BrZ23R8Cpdza",
)
# https://docs.djangoproject.com/en/dev/ref/settings/#test-runner
TEST_RUNNER = "django.test.runner.DiscoverRunner"
# `.test` covers ej.test, break.test, draft.test, and public.test.
ALLOWED_HOSTS = ["testserver", ".test", "localhost", "127.0.0.1"]

# PASSWORDS
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#password-hashers
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

# EMAIL
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#email-backend
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"

# CELERY
# ------------------------------------------------------------------------------
# Run tasks in-process. Tests must not need a Redis broker.
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True

# DEBUGGING FOR TEMPLATES
# ------------------------------------------------------------------------------
TEMPLATES[0]["OPTIONS"]["debug"] = True  # type: ignore[index]

# MEDIA
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#media-url
MEDIA_URL = "http://media.testserver/"

# BREAK scoring stays unconfigured in tests. A test that wants a call
# sets the URL and token itself and mocks the HTTP response.
BREAK_BACKEND_BASE_URL = ""
BREAK_SCORING_TOKEN = ""
# Your stuff...
# ------------------------------------------------------------------------------
