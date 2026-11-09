"""
Django settings for the Fuel Route Optimizer project.

Anything secret or environment-specific is read from environment variables.
For local development, copy `.env.example` to `.env` and fill it in.
"""

import os
from decimal import Decimal
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

load_dotenv(BASE_DIR / ".env")


def require_env(name: str) -> str:
    """Return an environment variable, failing loudly if it is missing."""
    value = os.environ.get(name)
    if not value:
        raise ImproperlyConfigured(f"Set the {name} environment variable (see .env.example).")
    return value


# --- Core -------------------------------------------------------------------

SECRET_KEY = require_env("DJANGO_SECRET_KEY")

DEBUG = os.environ.get("DJANGO_DEBUG", "False").lower() == "true"

ALLOWED_HOSTS = [
    host.strip()
    for host in os.environ.get("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")
    if host.strip()
]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "planner",
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


# --- Database & cache -------------------------------------------------------

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}

# In-process memory cache: zero setup, perfect for a single dev server.
# For several server processes, point this at Redis instead
# ("django.core.cache.backends.redis.RedisCache") — no code changes needed.
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
    }
}


# --- Auth, i18n, static -------------------------------------------------------

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"


# --- Django REST Framework ----------------------------------------------------

REST_FRAMEWORK = {
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    # A public, read-only API: no login, so skip the session/auth lookups.
    "DEFAULT_AUTHENTICATION_CLASSES": [],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.AllowAny"],
    "UNAUTHENTICATED_USER": None,
    "EXCEPTION_HANDLER": "planner.api.exceptions.api_exception_handler",
}


# --- Route planner ------------------------------------------------------------

# Vehicle assumptions from the brief.
VEHICLE_RANGE_MILES = 500
VEHICLE_MPG = 10

# How far off the route a station may be and still count as "on the way".
FUEL_CORRIDOR_MILES = 10
# Keep only the cheapest station in each stretch of this length, so the plan
# never stops twice within a few miles just to save a cent.
STOP_SPACING_MILES = 25
# The tank starts empty and is filled at the cheapest station this close to the start.
START_STATION_RADIUS_MILES = 25
# A cheaper station is only worth an extra stop if it saves at least this much
# per gallon. Set to 0 for the mathematically cheapest plan (more stops).
MIN_SAVING_PER_GALLON = Decimal("0.05")

# OpenRouteService (free routing API). Get a key at https://openrouteservice.org.
ORS_API_KEY = os.environ.get("ORS_API_KEY", "")
ORS_DIRECTIONS_URL = "https://api.openrouteservice.org/v2/directions/driving-car/geojson"
ORS_TIMEOUT_SECONDS = 15
# How far (meters) the routing API may look for the nearest road to the start
# and finish, e.g. when a town's center point is in a park.
ORS_SNAP_RADIUS_METERS = 5000

# Routes are cached so repeat requests (and the map page) never call the API again.
ROUTE_CACHE_SECONDS = 60 * 60 * 24
