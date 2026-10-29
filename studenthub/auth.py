"""Registration, login/logout and profile management."""
from __future__ import annotations

import hashlib
import logging

from flask import Blueprint, flash, redirect, render_template, request, session, url_for
from flask_login import (LoginManager, UserMixin, current_user, login_required,
                         login_user, logout_user)
from mysql.connector import errors
from werkzeug.security import check_password_hash, generate_password_hash

from . import db, utils
from .forms import LoginForm, PasswordForm, ProfileForm, RegisterForm

log = logging.getLogger("studenthub.auth")
bp = Blueprint("auth", __name__)
login_manager = LoginManager()
login_manager.login_view = "auth.login"
login_manager.login_message = "Please sign in to continue."
login_manager.login_message_category = "info"
login_manager.session_protection = "basic"

# Checked when an email is unknown so failed logins take similar time either way.
_DUMMY_HASH = generate_password_hash("timing-equaliser-password-1")


def _fingerprint(password_hash: str) -> str:
    return hashlib.sha256(password_hash.encode("utf-8")).hexdigest()[:16]


class User(UserMixin):
    def __init__(self, row: dict):
        self.id = row["id"]
        self.display_name = row["display_name"]
        self.email = row["email"]
        self.created_at = row.get("created_at")
        self._fingerprint = _fingerprint(row["password_hash"])

    def get_id(self) -> str:
        # Embedding a password fingerprint means changing the password signs out
        # every other session that still carries the old identifier.
        return f"{self.id}:{self._fingerprint}"

    @property
    def initials(self) -> str:
        parts = [p for p in self.display_name.split() if p]
        return "".join(p[0] for p in parts[:2]).upper() or "?"

    @property
    def first_name(self) -> str:
        return self.display_name.split()[0] if self.display_name.split() else self.display_name


@login_manager.user_loader
def load_user(identifier: str):
    user_id, _, fingerprint = identifier.partition(":")
    if not user_id.isdigit():
        return None
    row = db.query_one(
        "SELECT id, display_name, email, password_hash, created_at FROM users WHERE id = %s",
        (int(user_id),),
    )
    if row is None or _fingerprint(row["password_hash"]) != fingerprint:
        return None
    return User(row)


def email_taken(email: str, exclude_user_id: int | None = None) -> bool:
    if exclude_user_id is None:
        return db.query_one("SELECT id FROM users WHERE email = %s", (email,)) is not None
    return db.query_one("SELECT id FROM users WHERE email = %s AND id <> %s",
                        (email, exclude_user_id)) is not None


def _start_session(user: User, remember: bool) -> None:
    pending_flashes = session.get("_flashes")
    session.clear()  # a fresh session on login prevents session fixation
    if pending_flashes:
        session["_flashes"] = pending_flashes
    login_user(user, remember=remember)
    session.permanent = True


@bp.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))
    form = RegisterForm()
    if form.validate_on_submit():
        if email_taken(form.email.data):
            form.email.errors.append("An account with this email already exists.")
        else:
            try:
                result = db.execute(
                    "INSERT INTO users (display_name, email, password_hash) VALUES (%s, %s, %s)",
                    (form.display_name.data, form.email.data, generate_password_hash(form.password.data)),
                )
            except errors.IntegrityError:
                form.email.errors.append("An account with this email already exists.")
            else:
                row = db.query_one("SELECT id, display_name, email, password_hash, created_at "
                                   "FROM users WHERE id = %s", (result.lastrowid,))
                _start_session(User(row), remember=False)
                log.info("user registered id=%s", row["id"])
                flash(f"Welcome to StudentHub, {User(row).first_name}! Start by adding a subject.", "success")
                return redirect(url_for("main.dashboard"))
    return render_template("register.html", form=form)


@bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))
    form = LoginForm()
    if form.validate_on_submit():
        row = db.query_one(
            "SELECT id, display_name, email, password_hash, created_at FROM users WHERE email = %s",
            (form.email.data,),
        )
        valid = check_password_hash(row["password_hash"] if row else _DUMMY_HASH, form.password.data)
        if row and valid:
            db.execute("UPDATE users SET last_login_at = CURRENT_TIMESTAMP WHERE id = %s", (row["id"],))
            _start_session(User(row), remember=form.remember.data)
            target = request.args.get("next")
            return redirect(target if utils.is_safe_redirect(target) else url_for("main.dashboard"))
        log.info("failed login attempt")
        flash("Invalid email or password.", "danger")
    return render_template("login.html", form=form)


@bp.route("/logout", methods=["POST"])
@login_required
def logout():
    logout_user()
    session.clear()
    flash("You have been signed out.", "info")
    return redirect(url_for("auth.login"))


@bp.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    # Two forms share one page, so they use prefixes. CSRF for them is enforced by the
    # app-wide CSRFProtect (the template posts a standard csrf_token field).
    profile_form = ProfileForm(prefix="profile", meta={"csrf": False}, data={
        "display_name": current_user.display_name, "email": current_user.email})
    password_form = PasswordForm(prefix="password", meta={"csrf": False})
    action = request.form.get("action")

    if action == "profile" and profile_form.validate_on_submit():
        if email_taken(profile_form.email.data, exclude_user_id=current_user.id):
            profile_form.email.errors.append("Another account already uses this email.")
        else:
            try:
                db.execute("UPDATE users SET display_name = %s, email = %s WHERE id = %s",
                           (profile_form.display_name.data, profile_form.email.data, current_user.id))
            except errors.IntegrityError:
                profile_form.email.errors.append("Another account already uses this email.")
            else:
                flash("Profile updated.", "success")
                return redirect(url_for("auth.profile"))

    elif action == "password" and password_form.validate_on_submit():
        row = db.query_one("SELECT password_hash FROM users WHERE id = %s", (current_user.id,))
        if not check_password_hash(row["password_hash"], password_form.current_password.data):
            password_form.current_password.errors.append("Current password is incorrect.")
        elif password_form.new_password.data == password_form.current_password.data:
            password_form.new_password.errors.append("Choose a password different from the current one.")
        else:
            new_hash = generate_password_hash(password_form.new_password.data)
            db.execute("UPDATE users SET password_hash = %s WHERE id = %s", (new_hash, current_user.id))
            fresh = db.query_one("SELECT id, display_name, email, password_hash, created_at "
                                 "FROM users WHERE id = %s", (current_user.id,))
            _start_session(User(fresh), remember=False)  # keep this session, drop the others
            log.info("password changed user=%s", current_user.id)
            flash("Password changed. Other devices have been signed out.", "success")
            return redirect(url_for("auth.profile"))

    stats = db.query_one(
        """SELECT (SELECT COUNT(*) FROM subjects WHERE user_id = %s) AS subjects,
                  (SELECT COUNT(*) FROM assignments WHERE user_id = %s) AS assignments,
                  (SELECT COUNT(*) FROM study_sessions WHERE user_id = %s) AS sessions""",
        (current_user.id, current_user.id, current_user.id),
    )
    status_code = 400 if request.method == "POST" else 200
    return render_template("profile.html", profile_form=profile_form, password_form=password_form,
                           stats=stats), status_code
