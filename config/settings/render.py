"""Render demo deploy. One web service, Postgres from DATABASE_URL (Neon).

No Redis and no Celery worker: tasks run inside the request, the cache
lives in Postgres and WhiteNoise serves static files. EC2 stays on
`production.py`.
"""

from .base import *  # noqa: F403
from .base import DATABASES
from .base import MIDDLEWARE
from .base import env

# GENERAL
# ------------------------------------------------------------------------------
DEBUG = False
SECRET_KEY = env("DJANGO_SECRET_KEY")
# Render sets RENDER_EXTERNAL_HOSTNAME to the service's onrender.com host.
# The tenant middleware picks a company from the host, so every company's
# API host from DJANGO_DEMO_CHILDREN is allowed too. Same list seed_demo reads.
ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS", default=[])
RENDER_EXTERNAL_HOSTNAME = env("RENDER_EXTERNAL_HOSTNAME", default="")
if RENDER_EXTERNAL_HOSTNAME:
    ALLOWED_HOSTS.append(RENDER_EXTERNAL_HOSTNAME)
ALLOWED_HOSTS += [
    child["domain"]
    for child in env.json("DJANGO_DEMO_CHILDREN", default=[])
    if child.get("domain")
]

# DATABASES
# ------------------------------------------------------------------------------
DATABASES["default"]["CONN_MAX_AGE"] = env.int("CONN_MAX_AGE", default=60)
# Neon suspends idle compute, which drops pooled connections.
DATABASES["default"]["CONN_HEALTH_CHECKS"] = True

# CACHES
# ------------------------------------------------------------------------------
# Shared by every gunicorn worker, so the magic login throttles still hold.
# The table comes from `createcachetable` in compose/render/start.
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.db.DatabaseCache",
        "LOCATION": "django_cache",
    },
}

# SECURITY
# ------------------------------------------------------------------------------
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = env.bool("DJANGO_SECURE_SSL_REDIRECT", default=True)
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_CONTENT_TYPE_NOSNIFF = True
# Render's proxy is the only ingress, as in production.py.
TRUST_X_FORWARDED_FOR_IP = True

# FRONTEND
# ------------------------------------------------------------------------------
# Both Next.js apps call this API from their server and replay the cookies,
# so the browser never reaches this host and CORS is not involved. They send
# a fixed Origin (the admin's CLIENT_PORTAL_ORIGIN, the portal's APP_URL).
# Comma separated. Wildcard subdomains work, e.g. https://*.vercel.app
CSRF_TRUSTED_ORIGINS = env.list("DJANGO_CSRF_TRUSTED_ORIGINS", default=[])

# STATIC & MEDIA
# ------------------------------------------------------------------------------
MIDDLEWARE.insert(
    MIDDLEWARE.index("django.middleware.security.SecurityMiddleware") + 1,
    "whitenoise.middleware.WhiteNoiseMiddleware",
)
# Media stays on the instance disk, which Render wipes on every deploy.
# Nothing uploads files yet.
STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}

# EMAIL
# ------------------------------------------------------------------------------
# e.g. smtp+tls://user:password@smtp-relay.brevo.com:587
# Unset prints each mail, link included, to the Render logs.
vars().update(env.email_url("DJANGO_EMAIL_URL", default="consolemail://"))
DEFAULT_FROM_EMAIL = env(
    "DJANGO_DEFAULT_FROM_EMAIL",
    default="break-instantiation-backend <noreply@example.com>",
)
SERVER_EMAIL = DEFAULT_FROM_EMAIL

# ADMIN
# ------------------------------------------------------------------------------
ADMIN_URL = env("DJANGO_ADMIN_URL", default="admin/")

# CELERY
# ------------------------------------------------------------------------------
# No worker on the free plan. `.delay()` sends the mail inside the request.
# A failed send is logged by the task and the API still answers normally.
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = False
