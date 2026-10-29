"""Subject management.

Deletion policy: a subject that still has assignments or study sessions is only
deleted when the user explicitly confirms that those records are deleted with it
(``confirm_cascade=yes``). The delete runs in one transaction, and the database
foreign keys (ON DELETE CASCADE) guarantee no orphaned rows can remain.
"""
from __future__ import annotations

import logging

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from mysql.connector import errors

from . import db, utils
from .forms import SubjectForm

log = logging.getLogger("studenthub.subjects")
bp = Blueprint("subjects", __name__, url_prefix="/subjects")

SUBJECT_PALETTE = ["#4F46E5", "#0EA5E9", "#10B981", "#F59E0B", "#EF4444",
                   "#8B5CF6", "#EC4899", "#14B8A6", "#64748B", "#84CC16"]


def list_subjects(user_id: int) -> list[dict]:
    return db.query_all("SELECT id, name, code, color FROM subjects WHERE user_id = %s ORDER BY name",
                        (user_id,))


def subjects_with_stats(user_id: int, subject_id: int | None = None) -> list[dict]:
    sql = f"""
        SELECT s.id, s.name, s.code, s.description, s.color, s.created_at, s.updated_at,
               COUNT(a.id) AS total,
               COALESCE(SUM(a.status = 'completed'), 0) AS completed,
               COALESCE(SUM(a.status = 'in_progress'), 0) AS in_progress,
               COALESCE(SUM(a.status <> 'completed' AND {utils.DUE_AT_SQL} < %s), 0) AS overdue,
               (SELECT COUNT(*) FROM study_sessions ss
                 WHERE ss.subject_id = s.id AND ss.user_id = s.user_id) AS sessions,
               (SELECT COALESCE(SUM(ss.duration_minutes), 0) FROM study_sessions ss
                 WHERE ss.subject_id = s.id AND ss.user_id = s.user_id AND ss.is_completed = 1) AS study_minutes
          FROM subjects s
          LEFT JOIN assignments a ON a.subject_id = s.id AND a.user_id = s.user_id
         WHERE s.user_id = %s {"AND s.id = %s" if subject_id is not None else ""}
         GROUP BY s.id
         ORDER BY s.name
    """
    params: list = [utils.now_naive(), user_id]
    if subject_id is not None:
        params.append(subject_id)
    rows = db.query_all(sql, params)
    for row in rows:
        for key in ("total", "completed", "in_progress", "overdue", "sessions", "study_minutes"):
            row[key] = int(row[key])
        row["pending"] = row["total"] - row["completed"] - row["in_progress"]
        row["completion_pct"] = round(row["completed"] * 100 / row["total"]) if row["total"] else None
    return rows


def get_owned_subject(subject_id: int) -> dict:
    rows = subjects_with_stats(current_user.id, subject_id)
    return utils.get_or_404(rows[0] if rows else None)


def _next_color(user_id: int) -> str:
    used = db.query_value("SELECT COUNT(*) FROM subjects WHERE user_id = %s", (user_id,), default=0)
    return SUBJECT_PALETTE[int(used) % len(SUBJECT_PALETTE)]


@bp.route("/")
@login_required
def index():
    return render_template("subjects.html", subjects=subjects_with_stats(current_user.id))


@bp.route("/new", methods=["GET", "POST"])
@login_required
def create():
    form = SubjectForm()
    if request.method == "GET":
        form.color.data = _next_color(current_user.id)
    if form.validate_on_submit():
        try:
            result = db.execute(
                "INSERT INTO subjects (user_id, name, code, description, color) VALUES (%s, %s, %s, %s, %s)",
                (current_user.id, form.name.data, form.code.data, form.description.data, form.color.data.upper()),
            )
        except errors.IntegrityError:
            form.name.errors.append("You already have a subject with this name.")
        else:
            flash(f"Subject “{form.name.data}” created.", "success")
            return redirect(url_for("subjects.detail", subject_id=result.lastrowid))
    return render_template("subject_form.html", form=form, subject=None,
                           palette=SUBJECT_PALETTE), 400 if request.method == "POST" else 200


@bp.route("/<int:subject_id>")
@login_required
def detail(subject_id: int):
    subject = get_owned_subject(subject_id)
    now = utils.now_naive()
    assignments = [utils.decorate_assignment(row, now) for row in db.query_all(
        f"""SELECT a.id, a.title, a.due_date, a.due_time, a.priority, a.status
              FROM assignments a
             WHERE a.user_id = %s AND a.subject_id = %s
             ORDER BY a.status = 'completed', {utils.DUE_AT_SQL}""",
        (current_user.id, subject_id))]
    sessions = db.query_all(
        """SELECT id, title, session_date, start_time, duration_minutes, is_completed
             FROM study_sessions
            WHERE user_id = %s AND subject_id = %s
            ORDER BY session_date DESC, start_time DESC LIMIT 8""",
        (current_user.id, subject_id))
    return render_template("subject_detail.html", subject=subject, assignments=assignments, sessions=sessions)


@bp.route("/<int:subject_id>/edit", methods=["GET", "POST"])
@login_required
def edit(subject_id: int):
    subject = get_owned_subject(subject_id)
    form = SubjectForm(data={k: subject[k] for k in ("name", "code", "description", "color")})
    if form.validate_on_submit():
        try:
            db.execute(
                "UPDATE subjects SET name = %s, code = %s, description = %s, color = %s "
                "WHERE id = %s AND user_id = %s",
                (form.name.data, form.code.data, form.description.data, form.color.data.upper(),
                 subject_id, current_user.id),
            )
        except errors.IntegrityError:
            form.name.errors.append("You already have a subject with this name.")
        else:
            flash("Subject updated.", "success")
            return redirect(url_for("subjects.detail", subject_id=subject_id))
    return render_template("subject_form.html", form=form, subject=subject,
                           palette=SUBJECT_PALETTE), 400 if request.method == "POST" else 200


@bp.route("/<int:subject_id>/delete", methods=["POST"])
@login_required
def delete(subject_id: int):
    subject = get_owned_subject(subject_id)
    has_dependents = subject["total"] > 0 or subject["sessions"] > 0
    if has_dependents and request.form.get("confirm_cascade") != "yes":
        flash("This subject still has assignments or study sessions. Tick the confirmation box to delete "
              "them together with the subject.", "warning")
        return redirect(url_for("subjects.detail", subject_id=subject_id))
    with db.transaction():
        db.execute("DELETE FROM study_sessions WHERE subject_id = %s AND user_id = %s", (subject_id, current_user.id))
        db.execute("DELETE FROM assignments WHERE subject_id = %s AND user_id = %s", (subject_id, current_user.id))
        db.execute("DELETE FROM subjects WHERE id = %s AND user_id = %s", (subject_id, current_user.id))
    log.info("subject deleted id=%s user=%s assignments=%s sessions=%s",
             subject_id, current_user.id, subject["total"], subject["sessions"])
    flash(f"Subject “{subject['name']}” deleted.", "success")
    return redirect(url_for("subjects.index"))

