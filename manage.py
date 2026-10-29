"""Operational commands. Run inside the web container, for example:

    docker compose exec web python manage.py migration-status

Commands
    wait-db [--timeout N]   Wait until MySQL accepts connections (used at container start).
    migrate                 Apply pending migrations from database/migrations (safe to repeat).
    migration-status        Show which migrations are applied or pending.
"""
from __future__ import annotations

import argparse
import logging
import sys
import time

from mysql.connector import errors

from app import configure_logging
from config import get_config
from studenthub import db, migrations

log = logging.getLogger("studenthub.manage")


def load_settings() -> dict:
    config_class = get_config()
    settings = {key: getattr(config_class, key) for key in dir(config_class) if key.isupper()}
    config_class.validate(settings)
    return settings


def wait_db(settings: dict, timeout: int) -> int:
    deadline = time.monotonic() + timeout
    attempt = 0
    while True:
        attempt += 1
        try:
            conn = db.connect_direct(settings)
            conn.close()
            log.info("database is reachable host=%s attempt=%s", settings["DB_HOST"], attempt)
            return 0
        except errors.Error as exc:
            if time.monotonic() >= deadline:
                log.error("database not reachable after %ss host=%s error=%s",
                          timeout, settings["DB_HOST"], exc.__class__.__name__)
                return 1
            log.info("waiting for database host=%s attempt=%s", settings["DB_HOST"], attempt)
            time.sleep(min(2 * attempt, 5))


def run_migrations(settings: dict) -> int:
    conn = db.connect_direct(settings)
    try:
        applied = migrations.migrate(conn)
        if applied:
            log.info("applied migrations: %s", ", ".join(applied))
        return 0
    except migrations.MigrationError as exc:
        log.error("migration failed: %s", exc)
        return 1
    finally:
        conn.close()


def show_status(settings: dict) -> int:
    conn = db.connect_direct(settings)
    try:
        for version, name, state in migrations.status(conn):
            print(f"{version}  {name:<40} {state}")
        return 0
    finally:
        conn.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="StudentHub management commands")
    sub = parser.add_subparsers(dest="command", required=True)
    wait = sub.add_parser("wait-db", help="wait for MySQL to accept connections")
    wait.add_argument("--timeout", type=int, default=120)
    sub.add_parser("migrate", help="apply pending database migrations")
    sub.add_parser("migration-status", help="list migrations and their state")
    args = parser.parse_args(argv)

    settings = load_settings()
    configure_logging(settings["LOG_LEVEL"])
    if args.command == "wait-db":
        return wait_db(settings, args.timeout)
    if args.command == "migrate":
        return run_migrations(settings)
    return show_status(settings)


if __name__ == "__main__":
    sys.exit(main())
