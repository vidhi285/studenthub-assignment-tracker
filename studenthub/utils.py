"""Time helpers, constants and small shared utilities."""
from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta, timezone
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from flask import abort, current_app, request, url_for

STATUSES = {"pending": "Pending", "in_progress": "In progress", "completed": "Completed"}
PRIORITIES = {"low": "Low", "medium": "Medium", "high": "High"}
END_OF_DAY = time(23, 59, 59)
DUE_SOON_HOURS = 48

# SQL expression for an assignment's due moment (alias "a"). An assignment with no
# due time is due at the end of its due date. Used everywhere overdue is computed.
DUE_AT_SQL = "TIMESTAMP(a.due_date, COALESCE(a.due_time, '23:59:59'))"


def app_tz() -> ZoneInfo:
    return ZoneInfo(current_app.config["APP_TIMEZONE"])


def now_local() -> datetime:
    """Current time as an aware datetime in APP_TIMEZONE. Tests monkeypatch this."""
    return datetime.now(app_tz())


def now_naive() -> datetime:
    """Current local wall-clock time without tzinfo (comparable with DATE/TIME columns)."""
    return now_local().replace(tzinfo=None, microsecond=0)


def today() -> date:
    return now_local().date()


def week_start(day: date) -> date:
    return day - timedelta(days=day.weekday())  # weeks start on Monday


def utc_to_local(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(app_tz())


def local_to_utc_naive(value: datetime) -> datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=app_tz())
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def due_at(due_date: date, due_time: time | None) -> datetime:
    return datetime.combine(due_date, due_time or END_OF_DAY)


def decorate_assignment(row: dict, now: datetime | None = None) -> dict:
    """Add display flags (overdue / due soon) computed with the shared definition."""
    now = now or now_naive()
    moment = due_at(row["due_date"], row.get("due_time"))
    open_ = row["status"] != "completed"
    row["due_at"] = moment
    row["is_overdue"] = open_ and moment < now
    row["is_due_soon"] = open_ and not row["is_overdue"] and moment <= now + timedelta(hours=DUE_SOON_HOURS)
    return row


def parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        return None


def parse_month(value: str | None) -> tuple[int, int] | None:
    if not value:
        return None
    match = re.fullmatch(r"(\d{4})-(\d{2})", value.strip())
    if not match:
        return None
    year, month = int(match.group(1)), int(match.group(2))
    if not (1970 <= year <= 2100 and 1 <= month <= 12):
        return None
    return year, month


def add_months(year: int, month: int, delta: int) -> tuple[int, int]:
    index = year * 12 + (month - 1) + delta
    return index // 12, index % 12 + 1


def is_safe_redirect(target: str | None) -> bool:
    if not target or not target.startswith("/") or target.startswith("//") or "\\" in target:
        return False
    parts = urlsplit(target)
    return not parts.scheme and not parts.netloc


def escape_like(term: str) -> str:
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def url_with(**changes) -> str:
    """Current URL with some query parameters replaced (used by pagination/sorting)."""
    args = request.args.to_dict(flat=True)
    for key, value in changes.items():
        if value is None or value == "":
            args.pop(key, None)
        else:
            args[key] = value
    return url_for(request.endpoint, **(request.view_args or {}), **args)


def get_or_404(row: dict | None) -> dict:
    """Missing *or not owned* records both return 404, so IDs of other users' data leak nothing."""
    if row is None:
        abort(404)
    return row


def minutes_label(minutes: int | float | None) -> str:
    minutes = int(minutes or 0)
    hours, mins = divmod(minutes, 60)
    if hours and mins:
        return f"{hours}h {mins}m"
    if hours:
        return f"{hours}h"
    return f"{mins}m"
