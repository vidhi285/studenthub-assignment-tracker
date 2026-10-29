"""Ownership isolation, CSRF, headers, health checks, database failures and migrations."""
import re

import pytest

from app import create_app
from config import ConfigError, ProductionConfig, TestingConfig
from conftest import PASSWORD, create_subject, insert_assignment, insert_session, register, user_id
from studenthub import db as dbmod
from studenthub import migrations


@pytest.fixture()
def victim_data(auth_client, query):
    uid = user_id(query)
    subject_id = create_subject(auth_client, name="Private subject")
    assignment_id = insert_assignment(query, uid, subject_id, title="Private assignment", due_date="2030-01-01")
    session_id = insert_session(query, uid, subject_id, title="Private session", session_date="2030-01-01")
    return {"subject": subject_id, "assignment": assignment_id, "session": session_id}


def test_other_user_cannot_read_records(other_client, victim_data):
    for path in [f"/subjects/{victim_data['subject']}", f"/subjects/{victim_data['subject']}/edit",
                 f"/assignments/{victim_data['assignment']}", f"/assignments/{victim_data['assignment']}/edit",
                 f"/study/{victim_data['session']}/edit"]:
        response = other_client.get(path)
        assert response.status_code == 404, path
        assert "Private" not in response.get_data(as_text=True)
    listing = other_client.get("/assignments/?q=Private").get_data(as_text=True)
    assert "Private assignment" not in listing


def test_other_user_cannot_modify_or_delete_records(other_client, victim_data, query):
    s, a, ss = victim_data["subject"], victim_data["assignment"], victim_data["session"]
    attempts = [
        (f"/subjects/{s}/edit", {"name": "Hacked", "color": "#000000"}),
        (f"/subjects/{s}/delete", {"confirm_cascade": "yes"}),
        (f"/assignments/{a}/edit", {"title": "Hacked", "subject_id": str(s), "due_date": "2030-01-01",
                                    "priority": "low", "status": "pending"}),
        (f"/assignments/{a}/status", {"status": "completed"}),
        (f"/assignments/{a}/delete", {}),
        (f"/study/{ss}/edit", {"title": "Hacked", "subject_id": str(s), "session_date": "2030-01-01",
                              "start_time": "10:00", "duration_minutes": "60"}),
        (f"/study/{ss}/complete", {"completed": "1"}),
        (f"/study/{ss}/delete", {}),
    ]
    for path, data in attempts:
        assert other_client.post(path, data=data).status_code == 404, path
    assert query("SELECT name FROM subjects")[0]["name"] == "Private subject"
    assert query("SELECT title, status FROM assignments")[0] == {"title": "Private assignment", "status": "pending"}
    assert query("SELECT title, is_completed FROM study_sessions")[0] == {"title": "Private session", "is_completed": 0}


def test_cannot_attach_records_to_another_users_subject(other_client, victim_data, query):
    own_subject = create_subject(other_client, name="Mine")
    response = other_client.post("/assignments/new", data={
        "title": "Sneaky", "subject_id": str(victim_data["subject"]), "due_date": "2030-01-01",
        "priority": "low", "status": "pending"})
    assert response.status_code == 400
    response = other_client.post("/study/new", data={
        "title": "Sneaky", "subject_id": str(victim_data["subject"]), "session_date": "2030-01-01",
        "start_time": "10:00", "duration_minutes": "60"})
    assert response.status_code == 400
    assert query("SELECT COUNT(*) AS n FROM assignments WHERE title = 'Sneaky'")[0]["n"] == 0
    assert own_subject != victim_data["subject"]


def test_database_enforces_subject_ownership(query, auth_client, other_client, victim_data):
    import mysql.connector
    other_id = user_id(query, "grace@example.com")
    with pytest.raises(mysql.connector.IntegrityError):
        insert_assignment(query, other_id, victim_data["subject"], title="Direct insert")


@pytest.fixture()
def csrf_app():
    return create_app("testing", overrides={"WTF_CSRF_ENABLED": True})


def test_csrf_blocks_posts_without_token(csrf_app, query):
    client = csrf_app.test_client()
    response = client.post("/register", data={"display_name": "No Token", "email": "x@example.com",
                                              "password": PASSWORD, "confirm_password": PASSWORD})
    assert response.status_code == 400
    assert "Form expired" in response.get_data(as_text=True)
    assert query("SELECT id FROM users") == []


def test_csrf_accepts_valid_token(csrf_app, query):
    client = csrf_app.test_client()
    page = client.get("/register").get_data(as_text=True)
    token = re.search(r'name="csrf_token" type="hidden" value="([^"]+)"', page).group(1)
    response = client.post("/register", data={"csrf_token": token, "display_name": "With Token",
                                              "email": "y@example.com", "password": PASSWORD,
                                              "confirm_password": PASSWORD})
    assert response.status_code == 302
    dashboard = client.get("/dashboard").get_data(as_text=True)
    token = re.search(r'name="csrf_token" value="([^"]+)"', dashboard).group(1)
    assert client.post("/logout", data={}).status_code == 400  # logout needs a token too
    assert client.post("/logout", data={"csrf_token": token}).status_code == 302


def test_security_headers_and_cookie_flags(client, app):
    response = client.get("/login")
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert "default-src 'self'" in response.headers["Content-Security-Policy"]
    register_response = register(app.test_client(), email="cookie@example.com")
    cookie = register_response.headers.get("Set-Cookie", "")
    assert "HttpOnly" in cookie and "SameSite=Lax" in cookie


def test_health_endpoint_ok(client):
    response = client.get("/health")
    assert response.status_code == 200
    body = response.get_json()
    assert body["status"] == "ok" and body["database"] == "ok" and body["migrations_applied"] >= 1
    assert "version" in body
    assert client.get("/health/live").status_code == 200


@pytest.fixture()
def broken_db_app():
    return create_app("testing", overrides={"DB_PORT": 1})  # nothing listens on port 1


def test_health_reports_database_outage(broken_db_app):
    response = broken_db_app.test_client().get("/health")
    assert response.status_code == 503
    body = response.get_json()
    assert body == {**body, "status": "degraded", "database": "unavailable"}
    assert "password" not in response.get_data(as_text=True).lower()


def test_pages_show_friendly_503_when_database_is_down(broken_db_app):
    client = broken_db_app.test_client()
    response = client.post("/login", data={"email": "a@example.com", "password": PASSWORD})
    assert response.status_code == 503
    html = response.get_data(as_text=True)
    assert "Temporarily unavailable" in html and "Traceback" not in html
    assert client.get("/api/calendar?month=2026-01").status_code in (302, 503)


def test_unknown_page_returns_friendly_404(client):
    response = client.get("/definitely-not-here")
    assert response.status_code == 404
    assert "Page not found" in response.get_data(as_text=True)


def test_testing_config_refuses_non_test_database():
    with pytest.raises(ConfigError):
        TestingConfig.validate({"MYSQL_DATABASE": "studenthub"})


def test_production_config_requires_strong_secret():
    with pytest.raises(ConfigError):
        ProductionConfig.validate({"SECRET_KEY": "short", "MYSQL_PASSWORD": "x"})
    with pytest.raises(ConfigError):
        ProductionConfig.validate({"SECRET_KEY": "change-me-to-a-long-random-string", "MYSQL_PASSWORD": "x"})
    with pytest.raises(ConfigError):
        ProductionConfig.validate({"SECRET_KEY": "a" * 48, "MYSQL_PASSWORD": ""})
    ProductionConfig.validate({"SECRET_KEY": "a" * 48, "MYSQL_PASSWORD": "x"})


def test_migrations_are_idempotent_and_detect_edits(app, tmp_path):
    conn = dbmod.connect_direct(app.config)
    try:
        assert migrations.migrate(conn) == []  # already applied by the session fixture
        assert all(state == "applied" for _, _, state in migrations.status(conn))

        edited = tmp_path / "001_initial_schema.sql"
        edited.write_text(migrations.discover()[0].sql + "\n-- edited\n", encoding="utf-8")
        with pytest.raises(migrations.MigrationError):
            migrations.migrate(conn, directory=tmp_path)
    finally:
        conn.close()


def test_split_statements_ignores_comments():
    sql = "-- comment\nCREATE TABLE a (id INT);\n\n-- another\nALTER TABLE a\n  ADD COLUMN b INT;\n"
    assert migrations.split_statements(sql) == ["CREATE TABLE a (id INT)", "ALTER TABLE a\n  ADD COLUMN b INT"]


def test_bad_migration_filename_rejected(tmp_path):
    (tmp_path / "add_column.sql").write_text("SELECT 1;", encoding="utf-8")
    with pytest.raises(migrations.MigrationError):
        migrations.discover(tmp_path)
