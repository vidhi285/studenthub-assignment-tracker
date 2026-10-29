"""MySQL access layer.

* One lazily created connection pool per Flask app (and per Gunicorn worker).
* One pooled connection per request, stored on ``flask.g`` and returned on teardown.
* Every query is parameterised: callers pass SQL with %s placeholders plus a params tuple.
* Connection problems raise :class:`DatabaseUnavailable`, which the app turns into a
  friendly 503 page instead of a crash. The next request simply tries again.
"""
from __future__ import annotations

import logging
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import time as dtime
from datetime import timedelta
from typing import Any, Iterator

import mysql.connector
from mysql.connector import errors, pooling
from flask import current_app, g

log = logging.getLogger("studenthub.db")

_POOL_KEY = "studenthub_db_pool"
_pool_lock = threading.Lock()


class DatabaseUnavailable(RuntimeError):
    """The database could not be reached. Safe to retry later."""


@dataclass(frozen=True)
class ExecResult:
    lastrowid: int | None
    rowcount: int


def connection_kwargs(config: Any, include_database: bool = True) -> dict:
    kwargs = {
        "host": config["DB_HOST"],
        "port": int(config["DB_PORT"]),
        "user": config["MYSQL_USER"],
        "password": config["MYSQL_PASSWORD"],
        "charset": "utf8mb4",
        "collation": "utf8mb4_0900_ai_ci",
        "autocommit": False,
        "time_zone": "+00:00",  # CURRENT_TIMESTAMP values are stored as UTC
        "connection_timeout": 5,
    }
    if include_database:
        kwargs["database"] = config["MYSQL_DATABASE"]
    return kwargs


def connect_direct(config: Any) -> mysql.connector.MySQLConnection:
    """A standalone (non-pooled) connection, used by manage.py and tests."""
    return mysql.connector.connect(**connection_kwargs(config))


def init_app(app) -> None:
    app.teardown_appcontext(close_db)


def _get_pool() -> pooling.MySQLConnectionPool:
    app = current_app._get_current_object()
    pool = app.extensions.get(_POOL_KEY)
    if pool is not None:
        return pool
    with _pool_lock:
        pool = app.extensions.get(_POOL_KEY)
        if pool is None:
            try:
                pool = pooling.MySQLConnectionPool(
                    pool_name=f"studenthub_{id(app)}",
                    pool_size=app.config["DB_POOL_SIZE"],
                    pool_reset_session=True,
                    **connection_kwargs(app.config),
                )
            except errors.Error as exc:
                log.warning("database pool creation failed: %s", exc.__class__.__name__)
                raise DatabaseUnavailable("Could not connect to the database") from exc
            app.extensions[_POOL_KEY] = pool
            log.info("database pool ready host=%s db=%s size=%s",
                     app.config["DB_HOST"], app.config["MYSQL_DATABASE"], app.config["DB_POOL_SIZE"])
    return pool


def get_db():
    if "db" in g:
        return g.db
    pool = _get_pool()
    conn = None
    for attempt in range(5):
        try:
            conn = pool.get_connection()
            break
        except errors.PoolError:
            time.sleep(0.05 * (attempt + 1))  # pool momentarily exhausted
        except errors.Error as exc:
            raise DatabaseUnavailable("Could not get a database connection") from exc
    if conn is None:
        raise DatabaseUnavailable("Database connection pool exhausted")
    try:
        conn.ping(reconnect=True, attempts=2, delay=1)
    except errors.Error as exc:
        try:
            conn.close()
        except errors.Error:
            pass
        raise DatabaseUnavailable("Database did not answer") from exc
    g.db = conn
    g.db_in_transaction = False
    return conn


def close_db(_exc: BaseException | None = None) -> None:
    conn = g.pop("db", None)
    g.pop("db_in_transaction", None)
    if conn is None:
        return
    try:
        conn.rollback()
    except errors.Error:
        pass
    try:
        conn.close()  # returns the connection to the pool
    except errors.Error:
        pass


def _normalise(value: Any) -> Any:
    # mysql-connector returns TIME columns as timedelta; the app works with datetime.time.
    if isinstance(value, timedelta) and timedelta(0) <= value < timedelta(days=1):
        seconds = int(value.total_seconds())
        return dtime(seconds // 3600, (seconds % 3600) // 60, seconds % 60)
    return value


def _run(sql: str, params: tuple | list | dict, fetch: str | None):
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(sql, params)
        if fetch == "all":
            return [{k: _normalise(v) for k, v in row.items()} for row in cursor.fetchall()]
        if fetch == "one":
            row = cursor.fetchone()
            if row is not None:
                cursor.fetchall()
                return {k: _normalise(v) for k, v in row.items()}
            return None
        return ExecResult(cursor.lastrowid, cursor.rowcount)
    except (errors.OperationalError, errors.InterfaceError) as exc:
        raise DatabaseUnavailable("Lost connection to the database") from exc
    finally:
        cursor.close()


def query_all(sql: str, params: tuple | list | dict = ()) -> list[dict]:
    return _run(sql, params, "all")


def query_one(sql: str, params: tuple | list | dict = ()) -> dict | None:
    return _run(sql, params, "one")


def query_value(sql: str, params: tuple | list | dict = (), default: Any = None) -> Any:
    row = query_one(sql, params)
    if not row:
        return default
    value = next(iter(row.values()))
    return default if value is None else value


def execute(sql: str, params: tuple | list | dict = ()) -> ExecResult:
    """Run a write statement. Commits immediately unless inside ``transaction()``."""
    result = _run(sql, params, None)
    if not g.get("db_in_transaction"):
        try:
            g.db.commit()
        except (errors.OperationalError, errors.InterfaceError) as exc:
            raise DatabaseUnavailable("Lost connection while committing") from exc
    return result


@contextmanager
def transaction() -> Iterator[Any]:
    """Group several writes so they succeed or fail together."""
    conn = get_db()
    if g.get("db_in_transaction"):
        yield conn  # nested use joins the outer transaction
        return
    conn.rollback()  # discard the implicit read snapshot; start clean
    g.db_in_transaction = True
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        g.db_in_transaction = False


def check_health() -> dict:
    """Used by /health. Never raises; never exposes error details."""
    try:
        query_value("SELECT 1")
        applied = query_value("SELECT COUNT(*) FROM schema_migrations", default=0)
        return {"database": "ok", "migrations_applied": int(applied)}
    except DatabaseUnavailable:
        return {"database": "unavailable"}
    except errors.Error as exc:
        log.warning("health check query failed: %s", exc.__class__.__name__)
        return {"database": "error"}
