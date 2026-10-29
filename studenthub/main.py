"""Dashboard, calendar and analytics pages, plus the calendar JSON endpoint."""
from __future__ import annotations

from datetime import timedelta

from flask import Blueprint, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from . import stats, utils
from .subjects import subjects_with_stats

bp = Blueprint("main", __name__)

MAX_RANGE_DAYS = 366


@bp.route("/")
def index():
    return redirect(url_for("main.dashboard" if current_user.is_authenticated else "auth.login"))


@bp.route("/dashboard")
@login_required
def dashboard():
    uid = current_user.id
    today = utils.today()
    this_week = utils.week_start(today)
    overview = stats.assignment_overview(uid)
    weekly = stats.weekly_series(uid, this_week - timedelta(weeks=7), this_week)
    priorities = stats.priority_distribution(uid)
    chart_data = {
        "weekly": {"labels": [w["label"] for w in weekly],
                   "study_hours": [w["study_hours"] for w in weekly],
                   "assignments_completed": [w["assignments_completed"] for w in weekly]},
        "priority": {"labels": list(utils.PRIORITIES.values()), "values": list(priorities.values())},
    }
    return render_template(
        "dashboard.html",
        overview=overview,
        subject_total=stats.subject_count(uid),
        week_minutes=stats.study_minutes_between(uid, this_week, this_week + timedelta(days=6)),
        upcoming=stats.upcoming_assignments(uid),
        sessions=stats.recent_sessions(uid),
        subjects=subjects_with_stats(uid),
        chart_data=chart_data,
        has_weekly_data=any(w["study_minutes"] or w["assignments_completed"] for w in weekly),
        has_priority_data=any(priorities.values()),
    )


@bp.route("/calendar")
@login_required
def calendar():
    today = utils.today()
    month = utils.parse_month(request.args.get("month")) or (today.year, today.month)
    upcoming = [a for a in stats.upcoming_assignments(current_user.id, limit=40)
                if a["due_date"] <= today + timedelta(days=30)]
    return render_template("calendar.html", initial_month=f"{month[0]:04d}-{month[1]:02d}", upcoming=upcoming)


@bp.route("/api/calendar")
@login_required
def calendar_data():
    month = utils.parse_month(request.args.get("month"))
    if month is None:
        return jsonify(error="Use month=YYYY-MM"), 400
    data = stats.calendar_month(current_user.id, *month)
    for item in data["assignments"]:
        item["url"] = url_for("assignments.detail", assignment_id=item["id"])
    for item in data["sessions"]:
        item["url"] = url_for("study.edit", session_id=item["id"])
    return jsonify(data)


@bp.route("/analytics")
@login_required
def analytics():
    uid = current_user.id
    today = utils.today()
    default_from = utils.week_start(today) - timedelta(weeks=7)
    default_to = utils.week_start(today) + timedelta(days=6)
    date_from = utils.parse_date(request.args.get("from")) or default_from
    date_to = utils.parse_date(request.args.get("to")) or default_to
    if date_from > date_to or (date_to - date_from).days > MAX_RANGE_DAYS:
        flash("Choose a date range where the start is before the end and spans at most one year.", "warning")
        date_from, date_to = default_from, default_to

    weekly = stats.weekly_series(uid, utils.week_start(date_from), utils.week_start(date_to))
    breakdown = stats.status_breakdown(uid, date_from, date_to)
    workload = stats.upcoming_workload(uid)
    subjects = [s for s in subjects_with_stats(uid) if s["total"]]
    overview = stats.assignment_overview(uid)
    range_minutes = stats.study_minutes_between(uid, date_from, date_to)
    range_completed = sum(w["assignments_completed"] for w in weekly)

    chart_data = {
        "weekly": {"labels": [w["label"] for w in weekly],
                   "study_hours": [w["study_hours"] for w in weekly],
                   "assignments_completed": [w["assignments_completed"] for w in weekly]},
        "status": {"labels": ["Completed", "In progress", "Pending", "Overdue"],
                   "values": [breakdown["completed"], breakdown["in_progress"],
                              breakdown["pending"], breakdown["overdue"]]},
        "subjects": {"labels": [s["name"] for s in subjects],
                     "completed": [s["completed"] for s in subjects],
                     "remaining": [s["total"] - s["completed"] for s in subjects],
                     "colors": [s["color"] for s in subjects]},
        "workload": {"labels": [d["label"] for d in workload],
                     "assignments": [d["assignments"] for d in workload],
                     "study_hours": [round(d["study_minutes"] / 60, 2) for d in workload]},
    }
    week_count = max(len(weekly), 1)
    return render_template(
        "analytics.html", date_from=date_from, date_to=date_to, overview=overview, breakdown=breakdown,
        range_minutes=range_minutes, range_completed=range_completed,
        avg_weekly_minutes=round(sum(w["study_minutes"] for w in weekly) / week_count),
        chart_data=chart_data,
        has_weekly_data=any(w["study_minutes"] or w["assignments_completed"] for w in weekly),
        has_status_data=breakdown["total"] > 0,
        has_subject_data=bool(subjects),
        has_workload_data=any(d["assignments"] or d["study_minutes"] for d in workload),
    )
