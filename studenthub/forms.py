"""Server-side form definitions and validation (Flask-WTF also provides CSRF tokens)."""
from __future__ import annotations

import re
from datetime import timedelta

from flask_wtf import FlaskForm
from wtforms import (BooleanField, DateField, EmailField, IntegerField, PasswordField,
                     SelectField, StringField, TextAreaField, TimeField)
from wtforms.fields.choices import SelectChoice
from wtforms.validators import (DataRequired, Email, EqualTo, InputRequired, Length,
                                NumberRange, Optional, Regexp, ValidationError)

from . import utils

PASSWORD_HELP = "At least 8 characters, including a letter and a number."
DEFAULT_COLOR = "#4F46E5"


def strip(value):
    return value.strip() if isinstance(value, str) else value


def normalise_email(value):
    return value.strip().lower() if isinstance(value, str) else value


def none_if_blank(value):
    if isinstance(value, str):
        value = value.strip()
        return value or None
    return value


def strong_password(form, field):
    value = field.data or ""
    if len(value) < 8 or not re.search(r"[A-Za-z]", value) or not re.search(r"\d", value):
        raise ValidationError(PASSWORD_HELP)


class RegisterForm(FlaskForm):
    display_name = StringField("Full name", filters=[strip],
                               validators=[DataRequired(), Length(min=2, max=80)])
    email = EmailField("Email", filters=[normalise_email],
                       validators=[DataRequired(), Email(check_deliverability=False), Length(max=254)])
    password = PasswordField("Password", validators=[DataRequired(), Length(max=128), strong_password])
    confirm_password = PasswordField("Confirm password",
                                     validators=[DataRequired(), EqualTo("password", "Passwords do not match.")])


class LoginForm(FlaskForm):
    email = EmailField("Email", filters=[normalise_email], validators=[DataRequired(), Length(max=254)])
    password = PasswordField("Password", validators=[DataRequired(), Length(max=128)])
    remember = BooleanField("Keep me signed in")


class ProfileForm(FlaskForm):
    display_name = StringField("Full name", filters=[strip],
                               validators=[DataRequired(), Length(min=2, max=80)])
    email = EmailField("Email", filters=[normalise_email],
                       validators=[DataRequired(), Email(check_deliverability=False), Length(max=254)])


class PasswordForm(FlaskForm):
    current_password = PasswordField("Current password", validators=[DataRequired(), Length(max=128)])
    new_password = PasswordField("New password", validators=[DataRequired(), Length(max=128), strong_password])
    confirm_password = PasswordField("Confirm new password",
                                     validators=[DataRequired(), EqualTo("new_password", "Passwords do not match.")])


class SubjectForm(FlaskForm):
    name = StringField("Subject name", filters=[strip], validators=[DataRequired(), Length(max=100)])
    code = StringField("Subject code", filters=[none_if_blank],
                       validators=[Optional(), Length(max=20),
                                   Regexp(r"^[A-Za-z0-9 ._/-]+$", message="Use letters, numbers, spaces or - _ . /")])
    description = TextAreaField("Description", filters=[none_if_blank], validators=[Optional(), Length(max=1000)])
    color = StringField("Colour label", default=DEFAULT_COLOR, filters=[strip],
                        validators=[DataRequired(), Regexp(r"^#[0-9A-Fa-f]{6}$", message="Choose a valid colour.")])


class AssignmentForm(FlaskForm):
    title = StringField("Title", filters=[strip], validators=[DataRequired(), Length(max=200)])
    description = TextAreaField("Description", filters=[none_if_blank], validators=[Optional(), Length(max=5000)])
    subject_id = SelectField("Subject", coerce=int, validators=[InputRequired(message="Choose a subject.")])
    due_date = DateField("Due date", validators=[InputRequired(message="Choose a due date.")])
    due_time = TimeField("Due time", validators=[Optional()])
    priority = SelectField("Priority", choices=[SelectChoice(k, v) for k, v in utils.PRIORITIES.items()], default="medium")
    status = SelectField("Status", choices=[SelectChoice(k, v) for k, v in utils.STATUSES.items()], default="pending")

    def __init__(self, *args, original_due_date=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.original_due_date = original_due_date

    def validate_due_date(self, field):
        today = utils.today()
        if field.data is None:
            return
        if field.data > today + timedelta(days=5 * 365):
            raise ValidationError("Due date must be within the next five years.")
        # New assignments cannot be created in the past (usually a typo). Editing an
        # existing assignment may keep its original, possibly past, due date.
        if field.data < today and field.data != self.original_due_date:
            raise ValidationError("Due date cannot be in the past.")


class StudySessionForm(FlaskForm):
    title = StringField("Session title", filters=[strip], validators=[DataRequired(), Length(max=150)])
    subject_id = SelectField("Subject", coerce=int, validators=[InputRequired(message="Choose a subject.")])
    session_date = DateField("Date", validators=[InputRequired(message="Choose a date.")])
    start_time = TimeField("Start time", validators=[InputRequired(message="Choose a start time.")])
    duration_minutes = IntegerField("Duration (minutes)", default=60,
                                    validators=[InputRequired(message="Enter a duration."),
                                                NumberRange(min=5, max=720, message="Duration must be 5–720 minutes.")])
    notes = TextAreaField("Notes", filters=[none_if_blank], validators=[Optional(), Length(max=5000)])

    def validate_session_date(self, field):
        today = utils.today()
        if field.data is None:
            return
        if field.data < today - timedelta(days=365) or field.data > today + timedelta(days=2 * 365):
            raise ValidationError("Date must be within one year in the past and two years ahead.")


def subject_choices(subjects: list[dict]) -> list[SelectChoice]:
    return [SelectChoice(s["id"], f"{s['name']} ({s['code']})" if s.get("code") else s["name"]) for s in subjects]
