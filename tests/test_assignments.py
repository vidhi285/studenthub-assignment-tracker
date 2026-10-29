import re

from conftest import create_subject, insert_assignment, user_id


def assignment_data(subject_id, **overrides):
    data = {"title": "ER diagram", "description": "Draw the library schema", "subject_id": str(subject_id),
            "due_date": "2026-03-20", "due_time": "17:30", "priority": "high", "status": "pending"}
    data.update(overrides)
    return data


def test_create_assignment(auth_client, query, fixed_now):
    subject_id = create_subject(auth_client)
    response = auth_client.post("/assignments/new", data=assignment_data(subject_id))
    assert response.status_code == 302
    assignment_id = int(re.search(r"/assignments/(\d+)", response.headers["Location"]).group(1))
    row = query("SELECT * FROM assignments WHERE id = %s", (assignment_id,))[0]
    assert row["title"] == "ER diagram" and row["priority"] == "high" and row["status"] == "pending"
    assert str(row["due_date"]) == "2026-03-20" and str(row["due_time"]) == "17:30:00"
    assert row["completed_at"] is None and row["created_at"] is not None
    detail = auth_client.get(f"/assignments/{assignment_id}").get_data(as_text=True)
    assert "ER diagram" in detail and "17:30" in detail


def test_create_without_subjects_redirects_to_subject_form(auth_client):
    response = auth_client.get("/assignments/new")
    assert response.status_code == 302 and response.headers["Location"].endswith("/subjects/new")


def test_due_date_validation(auth_client, query, fixed_now):
    subject_id = create_subject(auth_client)
    past = auth_client.post("/assignments/new", data=assignment_data(subject_id, due_date="2026-03-10"))
    assert past.status_code == 400 and "cannot be in the past" in past.get_data(as_text=True)
    far = auth_client.post("/assignments/new", data=assignment_data(subject_id, due_date="2032-01-01"))
    assert far.status_code == 400 and "five years" in far.get_data(as_text=True)
    missing = auth_client.post("/assignments/new", data=assignment_data(subject_id, due_date=""))
    assert missing.status_code == 400
    assert auth_client.post("/assignments/new", data=assignment_data(subject_id, due_date="2026-03-11")).status_code == 302
    assert len(query("SELECT id FROM assignments")) == 1


def test_editing_keeps_original_past_due_date(auth_client, query, fixed_now):
    subject_id = create_subject(auth_client)
    assignment_id = insert_assignment(query, user_id(query), subject_id, title="Old", due_date="2026-02-01")
    keep = auth_client.post(f"/assignments/{assignment_id}/edit",
                            data=assignment_data(subject_id, title="Old renamed", due_date="2026-02-01", due_time=""))
    assert keep.status_code == 302
    row = query("SELECT title, due_time FROM assignments WHERE id = %s", (assignment_id,))[0]
    assert row["title"] == "Old renamed" and row["due_time"] is None
    move_past = auth_client.post(f"/assignments/{assignment_id}/edit",
                                 data=assignment_data(subject_id, due_date="2026-01-15"))
    assert move_past.status_code == 400


def test_status_transitions(auth_client, query):
    subject_id = create_subject(auth_client)
    assignment_id = insert_assignment(query, user_id(query), subject_id, due_date="2030-01-01")

    def status():
        return query("SELECT status, completed_at FROM assignments WHERE id = %s", (assignment_id,))[0]

    assert auth_client.post(f"/assignments/{assignment_id}/status", data={"status": "in_progress"}).status_code == 302
    assert status()["status"] == "in_progress" and status()["completed_at"] is None
    auth_client.post(f"/assignments/{assignment_id}/status", data={"status": "completed"})
    completed = status()
    assert completed["status"] == "completed" and completed["completed_at"] is not None
    auth_client.post(f"/assignments/{assignment_id}/status", data={"status": "pending"})  # reopen
    assert status() == {"status": "pending", "completed_at": None}
    assert auth_client.post(f"/assignments/{assignment_id}/status", data={"status": "archived"}).status_code == 400


def test_edit_to_completed_sets_completed_at(auth_client, query, fixed_now):
    subject_id = create_subject(auth_client)
    assignment_id = insert_assignment(query, user_id(query), subject_id)
    auth_client.post(f"/assignments/{assignment_id}/edit", data=assignment_data(subject_id, status="completed"))
    assert query("SELECT completed_at FROM assignments")[0]["completed_at"] is not None


def test_status_change_redirects_to_safe_next(auth_client, query):
    subject_id = create_subject(auth_client)
    assignment_id = insert_assignment(query, user_id(query), subject_id)
    ok = auth_client.post(f"/assignments/{assignment_id}/status", data={"status": "completed", "next": "/dashboard"})
    assert ok.headers["Location"].endswith("/dashboard")
    evil = auth_client.post(f"/assignments/{assignment_id}/status", data={"status": "pending", "next": "https://evil.test"})
    assert evil.headers["Location"].endswith(f"/assignments/{assignment_id}")


def test_delete_assignment(auth_client, query):
    subject_id = create_subject(auth_client)
    assignment_id = insert_assignment(query, user_id(query), subject_id)
    assert auth_client.post(f"/assignments/{assignment_id}/delete").status_code == 302
    assert query("SELECT id FROM assignments") == []
    assert auth_client.get(f"/assignments/{assignment_id}").status_code == 404


def _titles(html):
    return re.findall(r'class="row-title" href="/assignments/\d+">([^<]+)</a>', html)


def test_search_filters_and_sorting(auth_client, query, fixed_now):
    uid = user_id(query)
    maths = create_subject(auth_client, name="Maths", code="MA1")
    history = create_subject(auth_client, name="History", code="HI1")
    insert_assignment(query, uid, maths, title="Algebra sheet", priority="low", due_date="2026-03-25",
                      description="quadratic equations")
    insert_assignment(query, uid, maths, title="Geometry quiz", priority="high", due_date="2026-03-15")
    insert_assignment(query, uid, history, title="Essay draft", priority="medium", due_date="2026-03-05")  # overdue
    insert_assignment(query, uid, history, title="Timeline poster", status="completed", due_date="2026-03-01")

    get = lambda qs: _titles(auth_client.get("/assignments/?" + qs).get_data(as_text=True))  # noqa: E731
    assert get("q=quadratic") == ["Algebra sheet"]
    assert set(get(f"subject={maths}")) == {"Algebra sheet", "Geometry quiz"}
    assert get("status=completed") == ["Timeline poster"]
    assert get("status=overdue") == ["Essay draft"]
    assert set(get("status=open")) == {"Algebra sheet", "Geometry quiz", "Essay draft"}
    assert get("priority=high") == ["Geometry quiz"]
    assert get("due_from=2026-03-10&due_to=2026-03-20") == ["Geometry quiz"]
    assert get("status=open&sort=priority") == ["Geometry quiz", "Essay draft", "Algebra sheet"]
    # Default order: open work by due date, completed last.
    assert get("") == ["Essay draft", "Geometry quiz", "Algebra sheet", "Timeline poster"]
    # Unknown values are ignored instead of erroring.
    assert len(get("status=bogus&priority=x&sort=';DROP TABLE users;--&subject=999999")) == 4
    assert query("SELECT COUNT(*) AS n FROM users")[0]["n"] == 1


def test_search_treats_wildcards_literally(auth_client, query):
    uid = user_id(query)
    subject_id = create_subject(auth_client)
    insert_assignment(query, uid, subject_id, title="Score 100% on quiz")
    insert_assignment(query, uid, subject_id, title="Plain task")
    assert _titles(auth_client.get("/assignments/?q=%25").get_data(as_text=True)) == ["Score 100% on quiz"]
    assert _titles(auth_client.get("/assignments/?q=_").get_data(as_text=True)) == []


def test_pagination(auth_client, query):
    uid = user_id(query)
    subject_id = create_subject(auth_client)
    for i in range(13):
        insert_assignment(query, uid, subject_id, title=f"Task {i:02d}", due_date=f"2030-01-{i + 1:02d}")
    first = auth_client.get("/assignments/").get_data(as_text=True)
    second = auth_client.get("/assignments/?page=2").get_data(as_text=True)
    beyond = auth_client.get("/assignments/?page=99").get_data(as_text=True)
    assert len(_titles(first)) == 10 and len(_titles(second)) == 3
    assert "Showing 11–13 of 13" in second
    assert _titles(beyond) == _titles(second)  # clamped to the last page
