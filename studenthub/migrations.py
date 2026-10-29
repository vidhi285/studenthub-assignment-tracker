"""A small, forward-only SQL migration runner.

Migrations live in ``database/migrations`` and are named ``NNN_description.sql``.
Each file is applied once, in order, and recorded in ``schema_migrations`` together
with a SHA-256 checksum. Rules:

* Never edit a migration that has been applied anywhere; add a new file instead.
* Migrations only move forward. The runner never drops or downgrades anything.
* A MySQL named lock prevents two containers from migrating at the same time.
"""
from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger("studenthub.migrations")

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "database" / "migrations"
FILENAME_RE = re.compile(r"^(\d{3})_([a-z0-9_]+)\.sql$")
LOCK_NAME = "studenthub_schema_migrations"


class MigrationError(RuntimeError):
    pass


@dataclass(frozen=True)
class Migration:
    version: str
    name: str
    path: Path

    @property
    def sql(self) -> str:
        return self.path.read_text(encoding="utf-8")

    @property
    def checksum(self) -> str:
        return hashlib.sha256(self.sql.replace("\r\n", "\n").encode("utf-8")).hexdigest()


def discover(directory: Path = MIGRATIONS_DIR) -> list[Migration]:
    found = []
    for path in sorted(directory.glob("*.sql")):
        match = FILENAME_RE.match(path.name)
        if not match:
            raise MigrationError(f"Bad migration filename {path.name!r}; expected NNN_description.sql")
        found.append(Migration(match.group(1), match.group(2), path))
    versions = [m.version for m in found]
    if len(versions) != len(set(versions)):
        raise MigrationError("Two migration files share the same version number")
    return found


def split_statements(sql: str) -> list[str]:
    """Split a migration into statements. Comment lines (--) are dropped.

    Migrations must not use DELIMITER or stored procedures; one statement ends
    with a semicolon at the end of a line.
    """
    statements, current = [], []
    for line in sql.replace("\r\n", "\n").split("\n"):
        stripped = line.strip()
        if not stripped or stripped.startswith("--"):
            continue
        current.append(line)
        if stripped.endswith(";"):
            statement = "\n".join(current).strip().rstrip(";").strip()
            if statement:
                statements.append(statement)
            current = []
    leftover = "\n".join(current).strip()
    if leftover:
        statements.append(leftover)
    return statements


def _ensure_table(cursor) -> None:
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version     CHAR(3)      NOT NULL PRIMARY KEY,
            name        VARCHAR(150) NOT NULL,
            checksum    CHAR(64)     NOT NULL,
            applied_at  TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
        """
    )


def applied_versions(conn) -> dict[str, str]:
    cursor = conn.cursor()
    try:
        _ensure_table(cursor)
        cursor.execute("SELECT version, checksum FROM schema_migrations")
        return {version: checksum for version, checksum in cursor.fetchall()}
    finally:
        cursor.close()


def status(conn, directory: Path = MIGRATIONS_DIR) -> list[tuple[str, str, str]]:
    applied = applied_versions(conn)
    rows = []
    for migration in discover(directory):
        if migration.version not in applied:
            state = "pending"
        elif applied[migration.version] != migration.checksum:
            state = "CHANGED AFTER APPLY"
        else:
            state = "applied"
        rows.append((migration.version, migration.name, state))
    known = {m.version for m in discover(directory)}
    for version in sorted(set(applied) - known):
        rows.append((version, "(unknown to this code version)", "applied"))
    return rows


def migrate(conn, directory: Path = MIGRATIONS_DIR) -> list[str]:
    """Apply pending migrations. Returns the versions that were applied."""
    migrations = discover(directory)
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT GET_LOCK(%s, 60)", (LOCK_NAME,))
        (locked,) = cursor.fetchone()
        if locked != 1:
            raise MigrationError("Timed out waiting for the migration lock")
        try:
            applied = applied_versions(conn)
            known = {m.version for m in migrations}
            newer = sorted(set(applied) - known)
            if newer:
                # Happens after rolling back to an older image. The schema is left
                # untouched (never downgraded); additive migrations keep old code working.
                log.warning("database has migrations this code does not know: %s", ", ".join(newer))
            done = []
            for migration in migrations:
                if migration.version in applied:
                    if applied[migration.version] != migration.checksum:
                        raise MigrationError(
                            f"Migration {migration.path.name} was modified after being applied. "
                            "Restore the original file and add a new migration instead."
                        )
                    continue
                log.info("applying migration %s_%s", migration.version, migration.name)
                for statement in split_statements(migration.sql):
                    cursor.execute(statement)
                cursor.execute(
                    "INSERT INTO schema_migrations (version, name, checksum) VALUES (%s, %s, %s)",
                    (migration.version, migration.name, migration.checksum),
                )
                conn.commit()
                done.append(migration.version)
            if not done:
                log.info("database schema is up to date (%d migrations)", len(migrations))
            return done
        finally:
            cursor.execute("SELECT RELEASE_LOCK(%s)", (LOCK_NAME,))
            cursor.fetchall()
    except Exception:
        conn.rollback()
        raise
    finally:
        cursor.close()
