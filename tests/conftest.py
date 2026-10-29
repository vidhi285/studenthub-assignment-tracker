"""Shared pytest fixtures.

Tests run against a real, disposable MySQL database whose name must end in ``_test``
(TestingConfig refuses anything else). Every test starts with empty tables.

Defaults match the GitHub Actions MySQL service; override with environment variables
(DB_HOST, DB_PORT, MYSQL_DATABASE, MYSQL_USER, MYSQL_PASSWORD) if needed.
"""
from __future__ import annotations

import os
import re
from datetime import datetime
from zoneinfo import ZoneInfo

os.environ["APP_ENV"] = "testing"
os.environ.setdefault("DB_HOST", "127.0.0.1")
os.environ.setdefault("DB_PORT", "3306")
os.environ.setdefault("MYSQL_DATABASE", "studenthub_test")
os.environ.setdefault("MYSQL_USER", "studenthub")
os.environ.setdefault("MYSQL_PASSWORD", "test_password")
os.environ.setdefault("APP_TIMEZONE", "Asia/Kolkata")

import mysql.connector  # noqa: E402
import pytest  # noqa: E402

from app import create_app  # noqa: E402
from studenthub import db as dbmod  # noqa: E402
from studenthub import migrations, utils  # noqa: E402

TABLES = ("study_sessions", "assignments", "subjects", "users")
PASSWORD = "Password123"
FIXED_NOW = datetime(2026, 3, 11, 10, 0, tzinfo=ZoneInfo("Asia/Kolkata"))  # a Wednesday


@pytest.fixture(scope="session")
def app():
    application = create_app("testing")
    assert application.config["MYSQL_DATABASE"].endswith("_test")
    conn = dbmod.connect_direct(application.config)
    try:
        migrations.migrate(conn)
    finally:
        conn.close()
    return application


@pytest.fixture()
def db_conn(app):
    conn = mysql.connector.connect(**{**dbmod.connection_kwargs(app.config), "autocommit": True})
    yield conn
    conn.close()


@pytest.fixture(autouse=True)
def clean_tables(app, db_conn):
    cursor = db_conn.cursor()
    cursor.execute("SET FOREIGN_KEY_CHECKS = 0")
    for table in TABLES:
        cursor.execute(f"TRUNCATE TABLE {table}")
    cursor.execute("SET FOREIGN_KEY_CHECKS = 1")
    cursor.close()
    yield


@pytest.fixture()
def fixed_now(monkeypatch):
    """Freeze the app clock at FIXED_NOW (Wednesday 11 March 2026, 10:00 IST)."""
    monkeypatch.setattr(utils, "now_local", lambda: FIXED_NOW)
    return FIXED_NOW


@pytest.fixture()
def query(db_conn):
    def run(sql, params=()):
        cursor = db_conn.cursor(dictionary=True)
        cursor.execute(sql, params)
        rows = cursor.fetchall() if cursor.with_rows else []
        cursor.close()
        return rows
    return run


@pytest.fixture()
def client(app):
    return app.test_client()


def register(client, email="ada@example.com", password=PASSWORD, name="Ada Lovelace", follow=False):
    return client.post("/register", data={"display_name": name, "email": email, "password": password,
                                          "confirm_password": password}, follow_redirects=follow)


def login(client, email="ada@example.com", password=PASSWORD, follow=False, next_url=None):
    url = "/login" + (f"?next={next_url}" if next_url else "")
    return client.post(url, data={"email": email, "password": password}, follow_redirects=follow)


@pytest.fixture()
def auth_client(app):
    c = app.test_client()
    response = register(c)
    assert response.status_code == 302
    return c


@pytest.fixture()
def other_client(app):
    c = app.test_client()
    response = register(c, email="grace@example.com", name="Grace Hopper")
    assert response.status_code == 302
    return c


def user_id(query, email="ada@example.com"):
    return query("SELECT id FROM users WHERE email = %s", (email,))[0]["id"]


def create_subject(client, name="Databases", code="CS301", color="#4F46E5", query=None):
    response = client.post("/subjects/new", data={"name": name, "code": code, "description": "", "color": color})
    assert response.status_code == 302, response.get_data(as_text=True)
    return int(re.search(r"/subjects/(\d+)", response.headers["Location"]).group(1))


def insert_assignment(query, owner_id, subject_id, title="Task", due_date="2026-03-20", due_time=None,
                      status="pending", priority="medium", description=None, completed_at=None):
    if status == "completed" and completed_at is None:
        completed_at = "2026-03-10 06:00:00"
    query("""INSERT INTO assignments (user_id, subject_id, title, description, due_date, due_time, priority,
                                      status, completed_at)
             VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
          (owner_id, subject_id, title, description, due_date, due_time, priority, status, completed_at))
    return query("SELECT LAST_INSERT_ID() AS id")[0]["id"]


def insert_session(query, owner_id, subject_id, title="Study", session_date="2026-03-10", start_time="09:00",
                   duration=60, completed=False):
    query("""INSERT INTO study_sessions (user_id, subject_id, title, session_date, start_time, duration_minutes,
                                         is_completed, completed_at)
             VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
          (owner_id, subject_id, title, session_date, start_time, duration, int(completed),
           "2026-03-10 06:00:00" if completed else None))
    return query("SELECT LAST_INSERT_ID() AS id")[0]["id"]


def stat(html: str, name: str) -> str:
    match = re.search(rf'data-stat="{name}">([^<]*)<', html)
    assert match, f"stat {name} not found"
    return match.group(1).strip()
