from werkzeug.security import check_password_hash

from conftest import PASSWORD, login, register


def test_register_creates_user_with_hashed_password_and_logs_in(client, query):
    response = register(client, email="  Ada@Example.COM ")
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/dashboard")
    rows = query("SELECT email, display_name, password_hash FROM users")
    assert len(rows) == 1
    assert rows[0]["email"] == "ada@example.com"  # normalised
    assert rows[0]["password_hash"] != PASSWORD
    assert check_password_hash(rows[0]["password_hash"], PASSWORD)
    assert client.get("/dashboard").status_code == 200


def test_duplicate_email_is_rejected_case_insensitively(client, app, query):
    register(client)
    other = app.test_client()
    response = register(other, email="ADA@example.com", name="Someone Else")
    assert response.status_code == 200
    assert "already exists" in response.get_data(as_text=True)
    assert len(query("SELECT id FROM users")) == 1


def test_invalid_registration_input(client, query):
    cases = [
        {"display_name": "A", "email": "a@example.com", "password": PASSWORD, "confirm_password": PASSWORD},
        {"display_name": "Valid Name", "email": "not-an-email", "password": PASSWORD, "confirm_password": PASSWORD},
        {"display_name": "Valid Name", "email": "b@example.com", "password": "short1", "confirm_password": "short1"},
        {"display_name": "Valid Name", "email": "c@example.com", "password": "lettersonly", "confirm_password": "lettersonly"},
        {"display_name": "Valid Name", "email": "d@example.com", "password": PASSWORD, "confirm_password": "Different123"},
    ]
    for data in cases:
        response = client.post("/register", data=data)
        assert response.status_code == 200, data
        assert "invalid-feedback" in response.get_data(as_text=True)
    assert query("SELECT id FROM users") == []


def test_login_success_and_last_login_recorded(app, query):
    register(app.test_client())
    c = app.test_client()
    response = login(c)
    assert response.status_code == 302 and response.headers["Location"].endswith("/dashboard")
    assert query("SELECT last_login_at FROM users")[0]["last_login_at"] is not None


def test_login_failure_shows_generic_message(app):
    register(app.test_client())
    c = app.test_client()
    wrong_password = login(c, password="WrongPass999", follow=True).get_data(as_text=True)
    unknown_email = login(c, email="nobody@example.com", follow=True).get_data(as_text=True)
    assert "Invalid email or password." in wrong_password
    assert "Invalid email or password." in unknown_email
    assert c.get("/dashboard").status_code == 302


def test_login_redirects_to_safe_next_only(app):
    register(app.test_client())
    c = app.test_client()
    assert login(c, next_url="/calendar").headers["Location"].endswith("/calendar")
    c.post("/logout")
    assert login(c, next_url="//evil.example.com").headers["Location"].endswith("/dashboard")
    c.post("/logout")
    assert login(c, next_url="https://evil.example.com").headers["Location"].endswith("/dashboard")


def test_logout_requires_post_and_ends_session(auth_client):
    assert auth_client.get("/logout").status_code == 405
    response = auth_client.post("/logout")
    assert response.status_code == 302
    assert "/login" in auth_client.get("/dashboard").headers["Location"]


def test_protected_routes_redirect_anonymous_users(client):
    for path in ["/dashboard", "/subjects/", "/assignments/", "/calendar", "/study/", "/analytics", "/profile",
                 "/assignments/new", "/subjects/new", "/study/new", "/api/calendar?month=2026-03"]:
        response = client.get(path)
        assert response.status_code == 302, path
        assert "/login" in response.headers["Location"], path


def test_profile_update_and_duplicate_email(auth_client, other_client, query):
    response = auth_client.post("/profile", data={"action": "profile", "profile-display_name": "Ada King",
                                                  "profile-email": "Ada.King@Example.com"})
    assert response.status_code == 302
    row = query("SELECT display_name, email FROM users WHERE email = 'ada.king@example.com'")
    assert row and row[0]["display_name"] == "Ada King"

    clash = auth_client.post("/profile", data={"action": "profile", "profile-display_name": "Ada King",
                                               "profile-email": "grace@example.com"})
    assert clash.status_code == 400
    assert "Another account already uses this email." in clash.get_data(as_text=True)


def test_change_password_requires_current_password(auth_client, query):
    response = auth_client.post("/profile", data={
        "action": "password", "password-current_password": "WrongPass000",
        "password-new_password": "NewPassword456", "password-confirm_password": "NewPassword456"})
    assert response.status_code == 400
    assert "Current password is incorrect." in response.get_data(as_text=True)
    assert check_password_hash(query("SELECT password_hash FROM users")[0]["password_hash"], PASSWORD)


def test_change_password_success_signs_out_other_sessions(app, auth_client, query):
    second_device = app.test_client()
    login(second_device)
    assert second_device.get("/dashboard").status_code == 200

    response = auth_client.post("/profile", data={
        "action": "password", "password-current_password": PASSWORD,
        "password-new_password": "NewPassword456", "password-confirm_password": "NewPassword456"})
    assert response.status_code == 302
    assert auth_client.get("/dashboard").status_code == 200  # current session kept
    assert second_device.get("/dashboard").status_code == 302  # other session invalidated
    assert check_password_hash(query("SELECT password_hash FROM users")[0]["password_hash"], "NewPassword456")

    fresh = app.test_client()
    assert login(fresh, password=PASSWORD).status_code == 200
    assert login(fresh, password="NewPassword456").status_code == 302

