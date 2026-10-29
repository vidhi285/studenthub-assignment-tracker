from conftest import create_subject, insert_assignment, insert_session, user_id


def test_create_and_list_subject(auth_client, query):
    subject_id = create_subject(auth_client, name="Operating Systems", code="CS302", color="#10b981")
    row = query("SELECT name, code, color FROM subjects WHERE id = %s", (subject_id,))[0]
    assert row == {"name": "Operating Systems", "code": "CS302", "color": "#10B981"}
    page = auth_client.get("/subjects/").get_data(as_text=True)
    assert "Operating Systems" in page and "CS302" in page


def test_subject_validation_errors(auth_client, query):
    for data in [{"name": "", "color": "#4F46E5"}, {"name": "Valid", "color": "red"},
                 {"name": "Valid", "code": "bad<code>", "color": "#4F46E5"}, {"name": "x" * 101, "color": "#4F46E5"}]:
        response = auth_client.post("/subjects/new", data=data)
        assert response.status_code == 400, data
    assert query("SELECT id FROM subjects") == []


def test_subject_names_unique_per_user_only(auth_client, other_client, query):
    create_subject(auth_client, name="Physics")
    duplicate = auth_client.post("/subjects/new", data={"name": "Physics", "color": "#4F46E5"})
    assert duplicate.status_code == 400
    assert "already have a subject" in duplicate.get_data(as_text=True)
    create_subject(other_client, name="Physics")  # another user may reuse the name
    assert len(query("SELECT id FROM subjects WHERE name = 'Physics'")) == 2


def test_subject_detail_shows_assignments_and_stats(auth_client, query, fixed_now):
    subject_id = create_subject(auth_client)
    uid = user_id(query)
    insert_assignment(query, uid, subject_id, title="Done one", status="completed")
    insert_assignment(query, uid, subject_id, title="Late one", due_date="2026-03-01")
    page = auth_client.get(f"/subjects/{subject_id}").get_data(as_text=True)
    assert "Done one" in page and "Late one" in page
    assert "50%" in page and "Overdue" in page


def test_edit_subject(auth_client, query):
    subject_id = create_subject(auth_client)
    response = auth_client.post(f"/subjects/{subject_id}/edit",
                                data={"name": "Advanced Databases", "code": "", "description": "Room 4", "color": "#EF4444"})
    assert response.status_code == 302
    row = query("SELECT name, code, description, color FROM subjects WHERE id = %s", (subject_id,))[0]
    assert row == {"name": "Advanced Databases", "code": None, "description": "Room 4", "color": "#EF4444"}


def test_delete_empty_subject(auth_client, query):
    subject_id = create_subject(auth_client)
    response = auth_client.post(f"/subjects/{subject_id}/delete")
    assert response.status_code == 302
    assert query("SELECT id FROM subjects") == []


def test_delete_subject_with_dependents_requires_confirmation(auth_client, query):
    subject_id = create_subject(auth_client)
    uid = user_id(query)
    insert_assignment(query, uid, subject_id)
    insert_session(query, uid, subject_id)

    refused = auth_client.post(f"/subjects/{subject_id}/delete", follow_redirects=True)
    assert "Tick the confirmation box" in refused.get_data(as_text=True)
    assert len(query("SELECT id FROM subjects")) == 1

    confirmed = auth_client.post(f"/subjects/{subject_id}/delete", data={"confirm_cascade": "yes"})
    assert confirmed.status_code == 302
    assert query("SELECT id FROM subjects") == []
    assert query("SELECT id FROM assignments") == []
    assert query("SELECT id FROM study_sessions") == []


def test_missing_subject_returns_404(auth_client):
    assert auth_client.get("/subjects/9999").status_code == 404
    assert auth_client.post("/subjects/9999/delete").status_code == 404
