import os
from pathlib import Path
from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent.parent

# Carrega variáveis de config/.env (não versionado) para não precisar setar
# DEBUG/SECRET_KEY manualmente em cada terminal/sessão. Variáveis já definidas
# no ambiente (ex.: em produção) têm prioridade e não são sobrescritas.
from dotenv import load_dotenv
load_dotenv(BASE_DIR / ".env")

_DEV_SECRET_KEY = "flowspace-dev-secret-key-change-in-production"
SECRET_KEY = os.environ.get("SECRET_KEY", _DEV_SECRET_KEY)

# DEBUG is now opt-in (defaults to False) so a missing env var in production
# can never leak stack traces / settings / source code to visitors.
DEBUG = os.environ.get("DEBUG", "False") == "True"

if not DEBUG and SECRET_KEY == _DEV_SECRET_KEY:
    raise ImproperlyConfigured(
        "SECRET_KEY must be set via the SECRET_KEY environment variable when DEBUG=False."
    )

_default_hosts = "*" if DEBUG else "localhost,127.0.0.1,172.10.10.125"
ALLOWED_HOSTS = os.environ.get("ALLOWED_HOSTS", _default_hosts).split(",")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # API
    "rest_framework",
    "rest_framework_simplejwt",
    "rest_framework_simplejwt.token_blacklist",
    "corsheaders",
    # Apps
    "apps.accounts",
    "apps.projects",
    "apps.tasks",
    "apps.notifications",
    "apps.api",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "apps.accounts.middleware.ForcePasswordChangeMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF     = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
AUTH_USER_MODEL  = "accounts.User"
LOGIN_URL          = "/accounts/login/"
LOGIN_REDIRECT_URL = "/"
LOGOUT_REDIRECT_URL= "/accounts/login/"

TEMPLATES = [{
    "BACKEND": "django.template.backends.django.DjangoTemplates",
    "DIRS": [BASE_DIR / "templates"],
    "APP_DIRS": True,
    "OPTIONS": {"context_processors": [
        "django.template.context_processors.debug",
        "django.template.context_processors.request",
        "django.contrib.auth.context_processors.auth",
        "django.contrib.messages.context_processors.messages",
        "apps.projects.context_processors.sidebar",
    ]},
}]

DATABASES = {"default": {
    "ENGINE": "django.db.backends.sqlite3",
    "NAME":   BASE_DIR / "db.sqlite3",
}}

STATIC_URL       = "/static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT      = BASE_DIR / "staticfiles"
MEDIA_URL        = "/media/"
MEDIA_ROOT       = BASE_DIR / "media"

LANGUAGE_CODE      = "pt-br"
TIME_ZONE          = "America/Sao_Paulo"
USE_I18N           = True
USE_TZ             = True
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
EMAIL_BACKEND      = "django.core.mail.backends.console.EmailBackend"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 8}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# REST Framework
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework_simplejwt.authentication.JWTAuthentication",
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 50,
    "DEFAULT_THROTTLE_CLASSES": [
        "rest_framework.throttling.AnonRateThrottle",
        "rest_framework.throttling.UserRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {
        # Anonymous rate mainly gates the login/token-refresh endpoints (the
        # only AllowAny views), blunting credential brute-forcing.
        "anon": "20/min",
        "user": "1000/day",
    },
}

from datetime import timedelta
SIMPLE_JWT = {
    # Short-lived access token; refresh tokens rotate and old ones are blacklisted
    # (rest_framework_simplejwt.token_blacklist) so a leaked refresh token can't be reused.
    "ACCESS_TOKEN_LIFETIME":     timedelta(hours=1),
    "REFRESH_TOKEN_LIFETIME":    timedelta(days=14),
    "ROTATE_REFRESH_TOKENS":     True,
    "BLACKLIST_AFTER_ROTATION":  True,
}

# CORS: only wide-open in local DEBUG. In production, list explicit origins via
# the CORS_ALLOWED_ORIGINS env var (comma-separated). Credentials (cookies) are
# never allowed cross-origin — the web app is same-origin and the mobile app
# authenticates with JWT bearer tokens, not cookies.
CORS_ALLOW_ALL_ORIGINS = DEBUG
CORS_ALLOWED_ORIGINS   = [o for o in os.environ.get("CORS_ALLOWED_ORIGINS", "").split(",") if o]
CORS_ALLOW_CREDENTIALS = False

CSRF_TRUSTED_ORIGINS = [o for o in os.environ.get("CSRF_TRUSTED_ORIGINS", "").split(",") if o]

# ── Security hardening (only enforced outside DEBUG, since local dev usually
#    runs over plain HTTP) ────────────────────────────────────────────────────
SESSION_COOKIE_HTTPONLY = True
CSRF_COOKIE_HTTPONLY    = True
X_FRAME_OPTIONS         = "DENY"

if not DEBUG:
    SECURE_SSL_REDIRECT           = os.environ.get("SECURE_SSL_REDIRECT", "True") == "True"
    SESSION_COOKIE_SECURE         = True
    CSRF_COOKIE_SECURE            = True
    SECURE_HSTS_SECONDS           = 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD           = True
    SECURE_CONTENT_TYPE_NOSNIFF   = True
    SECURE_REFERRER_POLICY        = "same-origin"
