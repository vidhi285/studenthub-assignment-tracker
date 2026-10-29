"""Dashboard and analytics metrics.

Every number is calculated on the server from the logged-in user's own rows.
Definitions used throughout the app:
* Overdue: status is not 'completed' and the due moment (due date + due time,
  or 23:59:59 when no time is set) is earlier than the current local time.
* Upcoming: not completed, not overdue, due within the next 7 days.
* Study hours: only sessions marked as completed count.
* Weeks run Monday to Sunday in APP_TIMEZONE.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta

from . import db, utils

UPCOMING_DAYS = 7


def assignment_overview(user_id: int) -> dict:
    now = utils.now_naive()
    horizon = now + timedelta(days=UPCOMING_DAYS)
    row = db.query_one(
        f"""SELECT COUNT(*) AS total,
                   COALESCE(SUM(a.status = 'pending'), 0) AS pending,
                   COALESCE(SUM(a.status = 'in_progress'), 0) AS in_progress,
                   COALESCE(SUM(a.status = 'completed'), 0) AS completed,
                   COALESCE(SUM(a.status <> 'completed' AND {utils.DUE_AT_SQL} < %s), 0) AS overdue,
                   COALESCE(SUM(a.status <> 'completed' AND {utils.DUE_AT_SQL} >= %s
                                AND {utils.DUE_AT_SQL} <= %s), 0) AS upcoming
              FROM assignments a WHERE a.user_id = %s""",
        (now, now, horizon, user_id),
    )
    counts = {key: int(value) for key, value in row.items()}
    counts["completion_pct"] = round(counts["completed"] * 100 / counts["total"]) if counts["total"] else None
    return counts


def subject_count(user_id: int) -> int:
    return int(db.query_value("SELECT COUNT(*) FROM subjects WHERE user_id = %s", (user_id,), default=0))


def study_minutes_between(user_id: int, start: date, end: date) -> int:
    return int(db.query_value(
        """SELECT COALESCE(SUM(duration_minutes), 0) FROM study_sessions
            WHERE user_id = %s AND is_completed = 1 AND session_date BETWEEN %s AND %s""",
        (user_id, start, end), default=0))


def upcoming_assignments(user_id: int, limit: int = 6) -> list[dict]:
    now = utils.now_naive()
    rows = db.query_all(
        f"""SELECT a.id, a.title, a.due_date, a.due_time, a.priority, a.status,
                   s.name AS subject_name, s.color AS subject_color
              FROM assignments a JOIN subjects s ON s.id = a.subject_id AND s.user_id = a.user_id
             WHERE a.user_id = %s AND a.status <> 'completed'
             ORDER BY {utils.DUE_AT_SQL} ASC LIMIT %s""",
        (user_id, limit))
    return [utils.decorate_assignment(r, now) for r in rows]


def recent_sessions(user_id: int, limit: int = 5) -> list[dict]:
    return db.query_all(
        """SELECT ss.id, ss.title, ss.session_date, ss.start_time, ss.duration_minutes, ss.is_completed,
                  s.name AS subject_name, s.color AS subject_color
             FROM study_sessions ss JOIN subjects s ON s.id = ss.subject_id AND s.user_id = ss.user_id
            WHERE ss.user_id = %s AND ss.session_date <= %s
            ORDER BY ss.session_date DESC, ss.start_time DESC LIMIT %s""",
        (user_id, utils.today(), limit))


def priority_distribution(user_id: int) -> dict:
    rows = db.query_all(
        """SELECT priority, COUNT(*) AS n FROM assignments
            WHERE user_id = %s AND status <> 'completed' GROUP BY priority""", (user_id,))
    counts = {key: 0 for key in utils.PRIORITIES}
    for row in rows:
        counts[row["priority"]] = int(row["n"])
    return counts


def weekly_series(user_id: int, first_week: date, last_week: date) -> list[dict]:
    """Completed study hours and completed assignments per week (inclusive range)."""
    weeks = []
    cursor = first_week
    while cursor <= last_week:
        weeks.append({"week_start": cursor, "label": cursor.strftime("%d %b"),
                      "study_minutes": 0, "assignments_completed": 0})
        cursor += timedelta(days=7)
    if not weeks:
        return weeks
    index = {w["week_start"]: w for w in weeks}
    range_end = last_week + timedelta(days=6)

    for row in db.query_all(
            """SELECT session_date, SUM(duration_minutes) AS minutes FROM study_sessions
                WHERE user_id = %s AND is_completed = 1 AND session_date BETWEEN %s AND %s
                GROUP BY session_date""", (user_id, first_week, range_end)):
        index[utils.week_start(row["session_date"])]["study_minutes"] += int(row["minutes"])

    utc_from = utils.local_to_utc_naive(datetime.combine(first_week, time.min))
    utc_to = utils.local_to_utc_naive(datetime.combine(range_end + timedelta(days=1), time.min))
    for row in db.query_all(
            """SELECT completed_at FROM assignments
                WHERE user_id = %s AND status = 'completed' AND completed_at >= %s AND completed_at < %s""",
            (user_id, utc_from, utc_to)):
        week = utils.week_start(utils.utc_to_local(row["completed_at"]).date())
        if week in index:
            index[week]["assignments_completed"] += 1

    for week in weeks:
        week["study_hours"] = round(week["study_minutes"] / 60, 2)
    return weeks


def status_breakdown(user_id: int, start: date, end: date) -> dict:
    now = utils.now_naive()
    row = db.query_one(
        f"""SELECT COUNT(*) AS total,
                   COALESCE(SUM(a.status = 'completed'), 0) AS completed,
                   COALESCE(SUM(a.status = 'in_progress' AND {utils.DUE_AT_SQL} >= %s), 0) AS in_progress,
                   COALESCE(SUM(a.status = 'pending' AND {utils.DUE_AT_SQL} >= %s), 0) AS pending,
                   COALESCE(SUM(a.status <> 'completed' AND {utils.DUE_AT_SQL} < %s), 0) AS overdue
              FROM assignments a
             WHERE a.user_id = %s AND a.due_date BETWEEN %s AND %s""",
        (now, now, now, user_id, start, end))
    return {key: int(value) for key, value in row.items()}


def upcoming_workload(user_id: int, days: int = 14) -> list[dict]:
    start = utils.today()
    end = start + timedelta(days=days - 1)
    series = [{"date": start + timedelta(days=i), "assignments": 0, "study_minutes": 0} for i in range(days)]
    index = {d["date"]: d for d in series}
    for row in db.query_all(
            """SELECT due_date, COUNT(*) AS n FROM assignments
                WHERE user_id = %s AND status <> 'completed' AND due_date BETWEEN %s AND %s
                GROUP BY due_date""", (user_id, start, end)):
        index[row["due_date"]]["assignments"] = int(row["n"])
    for row in db.query_all(
            """SELECT session_date, SUM(duration_minutes) AS minutes FROM study_sessions
                WHERE user_id = %s AND is_completed = 0 AND session_date BETWEEN %s AND %s
                GROUP BY session_date""", (user_id, start, end)):
        index[row["session_date"]]["study_minutes"] = int(row["minutes"])
    for item in series:
        item["label"] = item["date"].strftime("%a %d")
    return series


def calendar_month(user_id: int, year: int, month: int) -> dict:
    first = date(year, month, 1)
    next_year, next_month = utils.add_months(year, month, 1)
    last = date(next_year, next_month, 1) - timedelta(days=1)
    now = utils.now_naive()
    assignments = []
    for row in db.query_all(
            """SELECT a.id, a.title, a.due_date, a.due_time, a.priority, a.status,
                      s.name AS subject_name, s.color AS subject_color
                 FROM assignments a JOIN subjects s ON s.id = a.subject_id AND s.user_id = a.user_id
                WHERE a.user_id = %s AND a.due_date BETWEEN %s AND %s
                ORDER BY a.due_date, a.due_time IS NULL, a.due_time""", (user_id, first, last)):
        utils.decorate_assignment(row, now)
        assignments.append({
            "id": row["id"], "title": row["title"], "date": row["due_date"].isoformat(),
            "time": row["due_time"].strftime("%H:%M") if row["due_time"] else None,
            "priority": row["priority"], "status": row["status"],
            "overdue": row["is_overdue"], "due_soon": row["is_due_soon"],
            "subject": row["subject_name"], "color": row["subject_color"],
        })
    sessions = [{
        "id": row["id"], "title": row["title"], "date": row["session_date"].isoformat(),
        "time": row["start_time"].strftime("%H:%M"), "duration": int(row["duration_minutes"]),
        "completed": bool(row["is_completed"]), "subject": row["subject_name"], "color": row["subject_color"],
    } for row in db.query_all(
        """SELECT ss.id, ss.title, ss.session_date, ss.start_time, ss.duration_minutes, ss.is_completed,
                  s.name AS subject_name, s.color AS subject_color
             FROM study_sessions ss JOIN subjects s ON s.id = ss.subject_id AND s.user_id = ss.user_id
            WHERE ss.user_id = %s AND ss.session_date BETWEEN %s AND %s
            ORDER BY ss.session_date, ss.start_time""", (user_id, first, last))]
    return {"month": f"{year:04d}-{month:02d}", "today": utils.today().isoformat(),
            "assignments": assignments, "sessions": sessions}
