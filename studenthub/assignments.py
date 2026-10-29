"""Assignment management: CRUD, status changes, search, filters, sorting and pagination."""
from __future__ import annotations

import math

from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from . import db, utils
from .forms import AssignmentForm, subject_choices
from .subjects import list_subjects

bp = Blueprint("assignments", __name__, url_prefix="/assignments")

SORTS = {
    "due_asc": ("Due date (soonest)", f"a.status = 'completed', {utils.DUE_AT_SQL} ASC, a.id ASC"),
    "due_desc": ("Due date (latest)", f"{utils.DUE_AT_SQL} DESC, a.id DESC"),
    "priority": ("Priority (high first)", f"FIELD(a.priority, 'high', 'medium', 'low'), {utils.DUE_AT_SQL} ASC"),
    "created_desc": ("Newest first", "a.created_at DESC, a.id DESC"),
    "created_asc": ("Oldest first", "a.created_at ASC, a.id ASC"),
}
STATUS_FILTERS = {**utils.STATUSES, "open": "Not completed", "overdue": "Overdue"}

# completed_at follows the status: set when first completed, cleared when reopened.
COMPLETED_AT_SQL = ("CASE WHEN %s = 'completed' THEN COALESCE(completed_at, CURRENT_TIMESTAMP) "
                    "ELSE NULL END")


def parse_filters(args, subject_ids: set[int]) -> dict:
    subject = args.get("subject", type=int)
    status = args.get("status", "")
    priority = args.get("priority", "")
    sort = args.get("sort", "due_asc")
    return {
        "q": (args.get("q") or "").strip()[:100],
        "subject": subject if subject in subject_ids else None,
        "status": status if status in STATUS_FILTERS else "",
        "priority": priority if priority in utils.PRIORITIES else "",
        "due_from": utils.parse_date(args.get("due_from")),
        "due_to": utils.parse_date(args.get("due_to")),
        "sort": sort if sort in SORTS else "due_asc",
        "page": max(args.get("page", 1, type=int) or 1, 1),
    }


def build_where(user_id: int, filters: dict, now) -> tuple[str, list]:
    """Only fixed SQL fragments are joined; every user value becomes a parameter."""
    clauses, params = ["a.user_id = %s"], [user_id]
    if filters["q"]:
        clauses.append("(a.title LIKE %s OR a.description LIKE %s)")
        term = f"%{utils.escape_like(filters['q'])}%"
        params += [term, term]
    if filters["subject"]:
        clauses.append("a.subject_id = %s")
        params.append(filters["subject"])
    if filters["status"] in utils.STATUSES:
        clauses.append("a.status = %s")
        params.append(filters["status"])
    elif filters["status"] == "open":
        clauses.append("a.status <> 'completed'")
    elif filters["status"] == "overdue":
        clauses.append(f"a.status <> 'completed' AND {utils.DUE_AT_SQL} < %s")
        params.append(now)
    if filters["priority"]:
        clauses.append("a.priority = %s")
        params.append(filters["priority"])
    if filters["due_from"]:
        clauses.append("a.due_date >= %s")
        params.append(filters["due_from"])
    if filters["due_to"]:
        clauses.append("a.due_date <= %s")
        params.append(filters["due_to"])
    return " AND ".join(clauses), params


def get_owned_assignment(assignment_id: int) -> dict:
    row = db.query_one(
        """SELECT a.*, s.name AS subject_name, s.code AS subject_code, s.color AS subject_color
             FROM assignments a JOIN subjects s ON s.id = a.subject_id AND s.user_id = a.user_id
            WHERE a.id = %s AND a.user_id = %s""",
        (assignment_id, current_user.id),
    )
    return utils.decorate_assignment(utils.get_or_404(row))


def _redirect_back(default: str):
    target = request.form.get("next") or request.args.get("next")
    return redirect(target if utils.is_safe_redirect(target) else default)


@bp.route("/")
@login_required
def index():
    subjects = list_subjects(current_user.id)
    filters = parse_filters(request.args, {s["id"] for s in subjects})
    now = utils.now_naive()
    where, params = build_where(current_user.id, filters, now)
    total = int(db.query_value(f"SELECT COUNT(*) FROM assignments a WHERE {where}", params, default=0))
    per_page = current_app.config["ASSIGNMENTS_PER_PAGE"]
    pages = max(math.ceil(total / per_page), 1)
    page = min(filters["page"], pages)
    rows = db.query_all(
        f"""SELECT a.id, a.title, a.description, a.due_date, a.due_time, a.priority, a.status,
                   a.created_at, s.id AS subject_id, s.name AS subject_name, s.color AS subject_color
              FROM assignments a JOIN subjects s ON s.id = a.subject_id AND s.user_id = a.user_id
             WHERE {where}
             ORDER BY {SORTS[filters['sort']][1]}
             LIMIT %s OFFSET %s""",
        [*params, per_page, (page - 1) * per_page],
    )
    assignments = [utils.decorate_assignment(r, now) for r in rows]
    active = any(filters[k] for k in ("q", "subject", "status", "priority", "due_from", "due_to"))
    return render_template("assignments.html", assignments=assignments, subjects=subjects, filters=filters,
                           total=total, page=page, pages=pages, sorts=SORTS, status_filters=STATUS_FILTERS,
                           filters_active=active)


def _form_with_subjects(subjects, **kwargs) -> AssignmentForm:
    form = AssignmentForm(**kwargs)
    form.subject_id.choices = subject_choices(subjects)
    return form


@bp.route("/new", methods=["GET", "POST"])
@login_required
def create():
    subjects = list_subjects(current_user.id)
    if not subjects:
        flash("Create a subject first, then add assignments to it.", "info")
        return redirect(url_for("subjects.create"))
    form = _form_with_subjects(subjects)
    if request.method == "GET":
        preset = request.args.get("subject", type=int)
        if preset in {s["id"] for s in subjects}:
            form.subject_id.data = preset
        preset_date = utils.parse_date(request.args.get("due_date"))
        form.due_date.data = preset_date if preset_date and preset_date >= utils.today() else None
    if form.validate_on_submit():
        result = db.execute(
            """INSERT INTO assignments
                    (user_id, subject_id, title, description, due_date, due_time, priority, status, completed_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s,
                        CASE WHEN %s = 'completed' THEN CURRENT_TIMESTAMP ELSE NULL END)""",
            (current_user.id, form.subject_id.data, form.title.data, form.description.data, form.due_date.data,
             form.due_time.data, form.priority.data, form.status.data, form.status.data),
        )
        flash("Assignment created.", "success")
        return redirect(url_for("assignments.detail", assignment_id=result.lastrowid))
    return render_template("assignment_form.html", form=form, assignment=None), \
        400 if request.method == "POST" else 200


@bp.route("/<int:assignment_id>")
@login_required
def detail(assignment_id: int):
    return render_template("assignment_detail.html", assignment=get_owned_assignment(assignment_id))


@bp.route("/<int:assignment_id>/edit", methods=["GET", "POST"])
@login_required
def edit(assignment_id: int):
    assignment = get_owned_assignment(assignment_id)
    subjects = list_subjects(current_user.id)
    form = _form_with_subjects(subjects, original_due_date=assignment["due_date"], data={
        k: assignment[k] for k in ("title", "description", "subject_id", "due_date", "due_time", "priority", "status")})
    if form.validate_on_submit():
        db.execute(
            f"""UPDATE assignments
                   SET subject_id = %s, title = %s, description = %s, due_date = %s, due_time = %s,
                       priority = %s, status = %s, completed_at = {COMPLETED_AT_SQL}
                 WHERE id = %s AND user_id = %s""",
            (form.subject_id.data, form.title.data, form.description.data, form.due_date.data, form.due_time.data,
             form.priority.data, form.status.data, form.status.data, assignment_id, current_user.id),
        )
        flash("Assignment updated.", "success")
        return redirect(url_for("assignments.detail", assignment_id=assignment_id))
    return render_template("assignment_form.html", form=form, assignment=assignment), \
        400 if request.method == "POST" else 200


@bp.route("/<int:assignment_id>/status", methods=["POST"])
@login_required
def set_status(assignment_id: int):
    assignment = get_owned_assignment(assignment_id)
    status = request.form.get("status", "")
    if status not in utils.STATUSES:
        abort(400)
    db.execute(
        f"UPDATE assignments SET status = %s, completed_at = {COMPLETED_AT_SQL} WHERE id = %s AND user_id = %s",
        (status, status, assignment_id, current_user.id),
    )
    messages = {"completed": "Marked as completed. Nice work!", "pending": "Assignment reopened.",
                "in_progress": "Marked as in progress."}
    flash(messages[status] if assignment["status"] != status else "Status unchanged.", "success")
    return _redirect_back(url_for("assignments.detail", assignment_id=assignment_id))


@bp.route("/<int:assignment_id>/delete", methods=["POST"])
@login_required
def delete(assignment_id: int):
    assignment = get_owned_assignment(assignment_id)
    db.execute("DELETE FROM assignments WHERE id = %s AND user_id = %s", (assignment_id, current_user.id))
    flash(f"Deleted “{assignment['title']}”.", "success")
    return _redirect_back(url_for("assignments.index"))
