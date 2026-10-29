"""Dashboard totals, calendar data and analytics, all with a frozen clock."""
import json
import re

from conftest import create_subject, insert_assignment, insert_session, stat, user_id


def seed(auth_client, query):
    uid = user_id(query)
    maths = create_subject(auth_client, name="Maths", code="MA1")
    physics = create_subject(auth_client, name="Physics", code="PH1")
    insert_assignment(query, uid, maths, title="Overdue A", due_date="2026-03-05", priority="high")
    insert_assignment(query, uid, maths, title="Overdue by time", due_date="2026-03-11", due_time="09:00")  # 1h ago
    insert_assignment(query, uid, maths, title="Due later today", due_date="2026-03-11", due_time="18:00",
                      status="in_progress")
    insert_assignment(query, uid, physics, title="Next week", due_date="2026-03-16", priority="low")
    insert_assignment(query, uid, physics, title="Far away", due_date="2026-05-01")
    insert_assignment(query, uid, physics, title="Done late", due_date="2026-03-01", status="completed",
                      completed_at="2026-03-10 05:00:00")
    insert_session(query, uid, maths, session_date="2026-03-09", duration=90, completed=True)   # this week
    insert_session(query, uid, maths, session_date="2026-03-10", duration=30, completed=False)  # not counted
    insert_session(query, uid, physics, session_date="2026-03-02", duration=60, completed=True)  # last week
    return uid, maths, physics


def test_dashboard_totals(auth_client, query, fixed_now):
    seed(auth_client, query)
    html = auth_client.get("/dashboard").get_data(as_text=True)
    assert stat(html, "total_assignments") == "6"
    assert stat(html, "pending") == "4"
    assert stat(html, "in_progress") == "1"
    assert stat(html, "completed") == "1"
    assert stat(html, "overdue") == "2"          # due date passed or due time passed today
    assert stat(html, "due_in_7_days") == "2"    # later today + next Monday
    assert stat(html, "subjects") == "2"
    assert stat(html, "study_this_week") == "1h 30m"
    assert "17% of all" in html                  # 1 of 6 completed


def test_dashboard_chart_data_matches_records(auth_client, query, fixed_now):
    seed(auth_client, query)
    html = auth_client.get("/dashboard").get_data(as_text=True)
    data = json.loads(re.search(r'<script id="chart-data" type="application/json">(.*?)</script>', html, re.S).group(1))
    assert data["weekly"]["labels"][-1] == "09 Mar"
    assert data["weekly"]["study_hours"][-2:] == [1.0, 1.5]
    assert data["weekly"]["assignments_completed"][-1] == 1  # completed 10 Mar (UTC) -> this week locally
    assert data["priority"]["values"] == [1, 3, 1]          # open work: low, medium, high


def test_dashboard_isolated_between_users(auth_client, other_client, query, fixed_now):
    seed(auth_client, query)
    html = other_client.get("/dashboard").get_data(as_text=True)
    assert stat(html, "total_assignments") == "0"
    assert stat(html, "subjects") == "0"
    assert "Overdue A" not in html
    assert "Set up StudentHub in three steps" in html


def test_empty_dashboard_shows_empty_states(auth_client, fixed_now):
    html = auth_client.get("/dashboard").get_data(as_text=True)
    assert "No activity in the last 8 weeks" in html
    assert 'id="weeklyChart"' not in html
    assert "You are all caught up" in html


def test_calendar_api_returns_month_items_with_flags(auth_client, other_client, query, fixed_now):
    seed(auth_client, query)
    data = auth_client.get("/api/calendar?month=2026-03").get_json()
    assert data["month"] == "2026-03" and data["today"] == "2026-03-11"
    by_title = {a["title"]: a for a in data["assignments"]}
    assert set(by_title) == {"Overdue A", "Overdue by time", "Due later today", "Next week", "Done late"}
    assert by_title["Overdue A"]["overdue"] is True
    assert by_title["Done late"]["overdue"] is False and by_title["Done late"]["status"] == "completed"
    assert by_title["Due later today"]["due_soon"] is True and by_title["Due later today"]["time"] == "18:00"
    assert by_title["Overdue A"]["url"].startswith("/assignments/")
    assert len(data["sessions"]) == 3
    assert other_client.get("/api/calendar?month=2026-03").get_json()["assignments"] == []
    assert auth_client.get("/api/calendar?month=2026-13").status_code == 400
    assert auth_client.get("/api/calendar").status_code == 400


def test_calendar_page_lists_upcoming_deadlines(auth_client, query, fixed_now):
    seed(auth_client, query)
    html = auth_client.get("/calendar?month=2026-04").get_data(as_text=True)
    assert 'data-initial-month="2026-04"' in html
    assert "Next week" in html and "Far away" not in html  # beyond 30 days


def test_analytics_page(auth_client, query, fixed_now):
    seed(auth_client, query)
    html = auth_client.get("/analytics?from=2026-03-01&to=2026-03-31").get_data(as_text=True)
    data = json.loads(re.search(r'<script id="chart-data" type="application/json">(.*?)</script>', html, re.S).group(1))
    # Assignments due in March: 5 (Far away is in May). Done late is completed; 2 overdue; 2 still open.
    assert data["status"]["values"] == [1, 1, 1, 2]
    assert data["subjects"]["labels"] == ["Maths", "Physics"]
    assert data["subjects"]["completed"] == [0, 1] and data["subjects"]["remaining"] == [3, 2]
    assert sum(data["weekly"]["study_hours"]) == 2.5
    assert len(data["workload"]["labels"]) == 14
    assert "2h 30m" in html  # study time in range


def test_analytics_invalid_range_falls_back(auth_client, fixed_now):
    html = auth_client.get("/analytics?from=2026-05-01&to=2026-01-01", follow_redirects=True).get_data(as_text=True)
    assert "Choose a date range" in html
    assert 'value="2026-01-19"' in html  # default: 8 weeks back from this Monday


def test_analytics_empty_states(auth_client, fixed_now):
    html = auth_client.get("/analytics").get_data(as_text=True)
    assert "No completed activity in this range" in html
    assert 'id="statusChart"' not in html
