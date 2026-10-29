from conftest import create_subject, insert_session, user_id


def session_data(subject, **overrides):
    data = {"title": "Revise joins", "subject_id": str(subject), "session_date": "2026-03-12",
            "start_time": "18:00", "duration_minutes": "90", "notes": "Chapter 5"}
    data.update(overrides)
    return data


def test_create_study_session(auth_client, query, fixed_now):
    subject_id = create_subject(auth_client)
    response = auth_client.post("/study/new", data=session_data(subject_id))
    assert response.status_code == 302
    assert "week=2026-03-09" in response.headers["Location"]  # Monday of that week
    row = query("SELECT * FROM study_sessions")[0]
    assert row["title"] == "Revise joins" and row["duration_minutes"] == 90
    assert str(row["start_time"]) == "18:00:00" and row["is_completed"] == 0 and row["completed_at"] is None


def test_study_session_validation(auth_client, query, fixed_now):
    subject_id = create_subject(auth_client)
    for overrides in [{"duration_minutes": "3"}, {"duration_minutes": "800"}, {"duration_minutes": "abc"},
                      {"start_time": ""}, {"session_date": "2024-01-01"}, {"title": ""}, {"subject_id": "99999"}]:
        response = auth_client.post("/study/new", data=session_data(subject_id, **overrides))
        assert response.status_code == 400, overrides
    assert query("SELECT id FROM study_sessions") == []


def test_complete_and_uncomplete_session(auth_client, query):
    subject_id = create_subject(auth_client)
    session_id = insert_session(query, user_id(query), subject_id)
    auth_client.post(f"/study/{session_id}/complete", data={"completed": "1"})
    row = query("SELECT is_completed, completed_at FROM study_sessions")[0]
    assert row["is_completed"] == 1 and row["completed_at"] is not None
    auth_client.post(f"/study/{session_id}/complete", data={"completed": "0"})
    assert query("SELECT is_completed, completed_at FROM study_sessions")[0] == {"is_completed": 0, "completed_at": None}


def test_planner_groups_sessions_by_week(auth_client, query, fixed_now):
    uid = user_id(query)
    subject_id = create_subject(auth_client)
    insert_session(query, uid, subject_id, title="This week session", session_date="2026-03-13", completed=True,
                   duration=45)
    insert_session(query, uid, subject_id, title="Next week session", session_date="2026-03-17")
    this_week = auth_client.get("/study/").get_data(as_text=True)
    assert "This week session" in this_week
    assert "Week of 09 Mar – 15 Mar 2026" in this_week
    assert "45m" in this_week
    next_week = auth_client.get("/study/?week=2026-03-18").get_data(as_text=True)
    assert "Next week session" in next_week and "Week of 16 Mar" in next_week
    assert "This week session" not in next_week.split("Next up")[0]


def test_edit_and_delete_session(auth_client, query, fixed_now):
    subject_id = create_subject(auth_client)
    session_id = insert_session(query, user_id(query), subject_id, session_date="2026-03-12")
    response = auth_client.post(f"/study/{session_id}/edit", data=session_data(subject_id, title="Moved",
                                                                              duration_minutes="30"))
    assert response.status_code == 302
    row = query("SELECT title, duration_minutes FROM study_sessions")[0]
    assert row == {"title": "Moved", "duration_minutes": 30}
    assert auth_client.post(f"/study/{session_id}/delete").status_code == 302
    assert query("SELECT id FROM study_sessions") == []


def test_create_session_requires_subject(auth_client):
    response = auth_client.get("/study/new")
    assert response.status_code == 302 and response.headers["Location"].endswith("/subjects/new")
