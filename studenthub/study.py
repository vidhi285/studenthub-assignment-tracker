"""Study planner: schedule, edit, complete and review study sessions, grouped by week."""
from __future__ import annotations

from datetime import datetime, timedelta

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from . import db, utils
from .forms import StudySessionForm, subject_choices
from .subjects import list_subjects

bp = Blueprint("study", __name__, url_prefix="/study")

SESSION_SELECT = """
    SELECT ss.id, ss.title, ss.notes, ss.session_date, ss.start_time, ss.duration_minutes,
           ss.is_completed, ss.completed_at, ss.created_at, ss.updated_at, ss.subject_id,
           s.name AS subject_name, s.color AS subject_color
      FROM study_sessions ss
      JOIN subjects s ON s.id = ss.subject_id AND s.user_id = ss.user_id
"""


def decorate_session(row: dict) -> dict:
    start = datetime.combine(row["session_date"], row["start_time"])
    row["starts_at"] = start
    row["ends_at"] = start + timedelta(minutes=int(row["duration_minutes"]))
    row["is_completed"] = bool(row["is_completed"])
    row["is_missed"] = not row["is_completed"] and row["ends_at"] < utils.now_naive()
    return row


def get_owned_session(session_id: int) -> dict:
    row = db.query_one(SESSION_SELECT + " WHERE ss.id = %s AND ss.user_id = %s", (session_id, current_user.id))
    return decorate_session(utils.get_or_404(row))


def _redirect_back(default: str):
    target = request.form.get("next")
    return redirect(target if utils.is_safe_redirect(target) else default)


@bp.route("/")
@login_required
def index():
    today = utils.today()
    requested = utils.parse_date(request.args.get("week"))
    start = utils.week_start(requested or today)
    end = start + timedelta(days=6)
    rows = [decorate_session(r) for r in db.query_all(
        SESSION_SELECT + """ WHERE ss.user_id = %s AND ss.session_date BETWEEN %s AND %s
                             ORDER BY ss.session_date, ss.start_time""",
        (current_user.id, start, end))]
    days = [{"date": start + timedelta(days=i), "sessions": []} for i in range(7)]
    for row in rows:
        days[(row["session_date"] - start).days]["sessions"].append(row)
    summary = {
        "scheduled_minutes": sum(int(r["duration_minutes"]) for r in rows),
        "completed_minutes": sum(int(r["duration_minutes"]) for r in rows if r["is_completed"]),
        "completed_count": sum(1 for r in rows if r["is_completed"]),
        "count": len(rows),
        "all_time_minutes": int(db.query_value(
            "SELECT COALESCE(SUM(duration_minutes), 0) FROM study_sessions WHERE user_id = %s AND is_completed = 1",
            (current_user.id,), default=0)),
    }
    summary["completion_pct"] = (round(summary["completed_minutes"] * 100 / summary["scheduled_minutes"])
                                 if summary["scheduled_minutes"] else None)
    upcoming = [decorate_session(r) for r in db.query_all(
        SESSION_SELECT + """ WHERE ss.user_id = %s AND ss.is_completed = 0
                               AND TIMESTAMP(ss.session_date, ss.start_time) >= %s
                             ORDER BY ss.session_date, ss.start_time LIMIT 5""",
        (current_user.id, utils.now_naive()))]
    return render_template("study_planner.html", days=days, week_start=start, week_end=end, today=today,
                           prev_week=start - timedelta(days=7), next_week=start + timedelta(days=7),
                           summary=summary, upcoming=upcoming, has_subjects=bool(list_subjects(current_user.id)))


def _form_with_subjects(subjects, **kwargs) -> StudySessionForm:
    form = StudySessionForm(**kwargs)
    form.subject_id.choices = subject_choices(subjects)
    return form


@bp.route("/new", methods=["GET", "POST"])
@login_required
def create():
    subjects = list_subjects(current_user.id)
    if not subjects:
        flash("Create a subject first, then plan study sessions for it.", "info")
        return redirect(url_for("subjects.create"))
    form = _form_with_subjects(subjects)
    if request.method == "GET":
        form.session_date.data = utils.parse_date(request.args.get("date")) or utils.today()
        preset = request.args.get("subject", type=int)
        if preset in {s["id"] for s in subjects}:
            form.subject_id.data = preset
    if form.validate_on_submit():
        db.execute(
            """INSERT INTO study_sessions
                   (user_id, subject_id, title, notes, session_date, start_time, duration_minutes)
               VALUES (%s, %s, %s, %s, %s, %s, %s)""",
            (current_user.id, form.subject_id.data, form.title.data, form.notes.data, form.session_date.data,
             form.start_time.data, form.duration_minutes.data),
        )
        flash("Study session scheduled.", "success")
        return redirect(url_for("study.index", week=utils.week_start(form.session_date.data).isoformat()))
    return render_template("study_form.html", form=form, study_session=None), \
        400 if request.method == "POST" else 200


@bp.route("/<int:session_id>/edit", methods=["GET", "POST"])
@login_required
def edit(session_id: int):
    study_session = get_owned_session(session_id)
    subjects = list_subjects(current_user.id)
    form = _form_with_subjects(subjects, data={k: study_session[k] for k in (
        "title", "subject_id", "session_date", "start_time", "duration_minutes", "notes")})
    if form.validate_on_submit():
        db.execute(
            """UPDATE study_sessions
                  SET subject_id = %s, title = %s, notes = %s, session_date = %s, start_time = %s,
                      duration_minutes = %s
                WHERE id = %s AND user_id = %s""",
            (form.subject_id.data, form.title.data, form.notes.data, form.session_date.data, form.start_time.data,
             form.duration_minutes.data, session_id, current_user.id),
        )
        flash("Study session updated.", "success")
        return redirect(url_for("study.index", week=utils.week_start(form.session_date.data).isoformat()))
    return render_template("study_form.html", form=form, study_session=study_session), \
        400 if request.method == "POST" else 200


@bp.route("/<int:session_id>/complete", methods=["POST"])
@login_required
def complete(session_id: int):
    study_session = get_owned_session(session_id)
    completed = request.form.get("completed", "1") == "1"
    db.execute(
        """UPDATE study_sessions
              SET is_completed = %s,
                  completed_at = CASE WHEN %s = 1 THEN COALESCE(completed_at, CURRENT_TIMESTAMP) ELSE NULL END
            WHERE id = %s AND user_id = %s""",
        (int(completed), int(completed), session_id, current_user.id),
    )
    flash("Session marked as completed." if completed else "Session marked as not completed.", "success")
    week = utils.week_start(study_session["session_date"]).isoformat()
    return _redirect_back(url_for("study.index", week=week))


@bp.route("/<int:session_id>/delete", methods=["POST"])
@login_required
def delete(session_id: int):
    study_session = get_owned_session(session_id)
    db.execute("DELETE FROM study_sessions WHERE id = %s AND user_id = %s", (session_id, current_user.id))
    flash(f"Deleted “{study_session['title']}”.", "success")
    week = utils.week_start(study_session["session_date"]).isoformat()
    return _redirect_back(url_for("study.index", week=week))
