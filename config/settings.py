"""
Django settings for the application microservice.
"""

from pathlib import Path
import sys

import environ


BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env(
    DEBUG=(bool, False),
    ALLOWED_HOSTS=(list, ["localhost", "127.0.0.1"]),
)
environ.Env.read_env(BASE_DIR / ".env")


# Core settings

SECRET_KEY = env("SECRET_KEY", default="django-insecure-application-dev-key")
DEBUG = env.bool("DEBUG")
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS")


# Application definition

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "apps.core",
    "apps.applications",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"


# Database

# If running under pytest or manage.py test and USE_POSTGRES_FOR_TESTS is not enabled,
# use an in-memory SQLite database to allow offline/local unit tests to run fast without requiring a live Postgres instance.
if (
    "pytest" in sys.modules
    or any("pytest" in arg for arg in sys.argv)
    or "test" in sys.argv
) and not env.bool("USE_POSTGRES_FOR_TESTS", default=False):
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": ":memory:",
        }
    }
else:
    database_url = env("DATABASE_URL", default="").strip()

    if database_url:
        DATABASES = {"default": env.db("DATABASE_URL")}
    else:
        DATABASES = {
            "default": {
                "ENGINE": "django.db.backends.postgresql",
                "NAME": env("POSTGRES_DB", default="db_applications"),
                "USER": env("POSTGRES_USER", default="postgres"),
                "PASSWORD": env("POSTGRES_PASSWORD", default="postgrespassword"),
                "HOST": env("POSTGRES_HOST", default="localhost"),
                "PORT": env.int("POSTGRES_PORT", default=5432),
            }
        }


# Password validation

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]


# Internationalization

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True


# Static files

STATIC_URL = "static/"


# Email

MAILERS = {
    "default": {
        "BACKEND": "django.core.mail.backends.console.EmailBackend",
    },
}


# Django REST Framework (ADR-002 Stateless RS256 JWT Authentication)

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "apps.core.authentication.RS256JWTAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
}


# JWT Cryptographic & OAuth2 Specifications (ADR-002)

JWT_PUBLIC_KEY_PATH = env("JWT_PUBLIC_KEY_PATH", default="certs/jwt_public.pem")
JWT_PUBLIC_KEY = env("JWT_PUBLIC_KEY", default="")
JWT_ISSUER = env("JWT_ISSUER", default="https://auth.conectanexus.ufps.edu.co")
JWT_AUDIENCES = ["conecta-nexus-gateway", "conecta-nexus-services"]

# Inter-Service Communication Settings
PROFILE_SERVICE_URL = env("PROFILE_SERVICE_URL", default="http://profile:8000")
INTERNAL_SERVICE_TOKEN = env("INTERNAL_SERVICE_TOKEN", default="")
CHALLENGE_SERVICE_URL = env("CHALLENGE_SERVICE_URL", default="http://challenge:8000")


