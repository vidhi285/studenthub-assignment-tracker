"""Application configuration.

All settings come from environment variables so the same Docker image can run
locally, in CI and in production. See .env.example for the full list.
"""
from __future__ import annotations

import os
from datetime import timedelta

PLACEHOLDER_SECRET = "change-me-to-a-long-random-string"


def _bool(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None or value == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _int(name: str, default: int) -> int:
    value = os.environ.get(name, "")
    try:
        return int(value) if value.strip() else default
    except ValueError as exc:
        raise RuntimeError(f"Environment variable {name} must be an integer, got {value!r}") from exc


class ConfigError(RuntimeError):
    """Raised when required configuration is missing or unsafe."""


class Config:
    APP_ENV = "development"
    DEBUG = False
    TESTING = False

    SECRET_KEY = os.environ.get("SECRET_KEY", "")

    DB_HOST = os.environ.get("DB_HOST", "db")
    DB_PORT = _int("DB_PORT", 3306)
    MYSQL_DATABASE = os.environ.get("MYSQL_DATABASE", "studenthub")
    MYSQL_USER = os.environ.get("MYSQL_USER", "studenthub")
    MYSQL_PASSWORD = os.environ.get("MYSQL_PASSWORD", "")
    DB_POOL_SIZE = _int("DB_POOL_SIZE", 5)

    # Calendar dates and times typed by users are interpreted in this zone.
    # Audit timestamps (created_at, updated_at, completed_at) are stored in UTC.
    APP_TIMEZONE = os.environ.get("APP_TIMEZONE", "Asia/Kolkata")
    APP_VERSION = os.environ.get("APP_VERSION", "dev")
    LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()
    TRUST_PROXY = _bool("TRUST_PROXY", False)

    SESSION_COOKIE_NAME = "studenthub_session"
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = False
    REMEMBER_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_SAMESITE = "Lax"
    REMEMBER_COOKIE_SECURE = False
    REMEMBER_COOKIE_DURATION = timedelta(days=14)
    PERMANENT_SESSION_LIFETIME = timedelta(days=7)

    WTF_CSRF_ENABLED = True
    WTF_CSRF_TIME_LIMIT = None  # token lives as long as the session
    MAX_CONTENT_LENGTH = 1 * 1024 * 1024

    ASSIGNMENTS_PER_PAGE = 10

    @classmethod
    def validate(cls, settings: dict) -> None:
        if not settings.get("SECRET_KEY"):
            raise ConfigError("SECRET_KEY is not set. Copy .env.example to .env and set a random value.")


class DevelopmentConfig(Config):
    APP_ENV = "development"
    DEBUG = False  # Gunicorn serves the app even locally; keep the debugger off.


class ProductionConfig(Config):
    APP_ENV = "production"
    SESSION_COOKIE_SECURE = True
    REMEMBER_COOKIE_SECURE = True

    @classmethod
    def validate(cls, settings: dict) -> None:
        secret = settings.get("SECRET_KEY", "")
        if not secret or secret == PLACEHOLDER_SECRET or len(secret) < 32:
            raise ConfigError("Production requires SECRET_KEY with at least 32 random characters.")
        if not settings.get("MYSQL_PASSWORD"):
            raise ConfigError("Production requires MYSQL_PASSWORD.")


class TestingConfig(Config):
    APP_ENV = "testing"
    TESTING = True
    SECRET_KEY = "testing-secret-key-not-for-production"
    WTF_CSRF_ENABLED = False  # test_security.py re-enables it explicitly
    DB_HOST = os.environ.get("DB_HOST", "127.0.0.1")
    MYSQL_DATABASE = os.environ.get("MYSQL_DATABASE", "studenthub_test")
    DB_POOL_SIZE = 3

    @classmethod
    def validate(cls, settings: dict) -> None:
        if not settings["MYSQL_DATABASE"].endswith("_test"):
            raise ConfigError(
                "Refusing to run tests: MYSQL_DATABASE must end with '_test' so tests "
                "can never touch development or production data."
            )


CONFIGS = {
    "development": DevelopmentConfig,
    "production": ProductionConfig,
    "testing": TestingConfig,
}


def get_config(name: str | None = None) -> type[Config]:
    env = (name or os.environ.get("APP_ENV") or "development").strip().lower()
    if env not in CONFIGS:
        raise ConfigError(f"Unknown APP_ENV {env!r}. Use one of: {', '.join(CONFIGS)}")
    return CONFIGS[env]
