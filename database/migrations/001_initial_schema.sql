-- 001_initial_schema.sql
-- Initial StudentHub schema. Applied automatically by `python manage.py migrate`,
-- which the web container runs on every start. Safe to re-run: every statement uses
-- IF NOT EXISTS and the runner records the migration so it is applied only once.
--
-- Time conventions:
--   * created_at / updated_at / completed_at are UTC (connections use time_zone '+00:00').
--   * due_date, due_time, session_date and start_time are wall-clock values in APP_TIMEZONE.

CREATE TABLE IF NOT EXISTS users (
    id             INT UNSIGNED  NOT NULL AUTO_INCREMENT,
    display_name   VARCHAR(80)   NOT NULL,
    email          VARCHAR(254)  NOT NULL COMMENT 'stored trimmed and lower-cased',
    password_hash  VARCHAR(255)  NOT NULL,
    last_login_at  TIMESTAMP     NULL DEFAULT NULL,
    created_at     TIMESTAMP     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at     TIMESTAMP     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uq_users_email (email)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS subjects (
    id           INT UNSIGNED  NOT NULL AUTO_INCREMENT,
    user_id      INT UNSIGNED  NOT NULL,
    name         VARCHAR(100)  NOT NULL,
    code         VARCHAR(20)   NULL DEFAULT NULL,
    description  VARCHAR(1000) NULL DEFAULT NULL,
    color        CHAR(7)       NOT NULL DEFAULT '#4F46E5',
    created_at   TIMESTAMP     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at   TIMESTAMP     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uq_subjects_user_name (user_id, name),
    UNIQUE KEY uq_subjects_id_user (id, user_id),
    CONSTRAINT fk_subjects_user FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE,
    CONSTRAINT chk_subjects_color CHECK (REGEXP_LIKE(color, '^#[0-9A-Fa-f]{6}$'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- The composite foreign key (subject_id, user_id) -> subjects (id, user_id) guarantees at
-- the database level that an assignment can only reference a subject of the same user.
CREATE TABLE IF NOT EXISTS assignments (
    id            INT UNSIGNED  NOT NULL AUTO_INCREMENT,
    user_id       INT UNSIGNED  NOT NULL,
    subject_id    INT UNSIGNED  NOT NULL,
    title         VARCHAR(200)  NOT NULL,
    description   TEXT          NULL,
    due_date      DATE          NOT NULL,
    due_time      TIME          NULL DEFAULT NULL,
    priority      ENUM('low', 'medium', 'high')                NOT NULL DEFAULT 'medium',
    status        ENUM('pending', 'in_progress', 'completed')  NOT NULL DEFAULT 'pending',
    completed_at  TIMESTAMP     NULL DEFAULT NULL,
    created_at    TIMESTAMP     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at    TIMESTAMP     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    KEY idx_assignments_user_due (user_id, due_date),
    KEY idx_assignments_user_status (user_id, status),
    KEY idx_assignments_user_priority (user_id, priority),
    KEY idx_assignments_user_completed (user_id, completed_at),
    KEY idx_assignments_subject (subject_id, user_id),
    CONSTRAINT fk_assignments_user FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE,
    CONSTRAINT fk_assignments_subject FOREIGN KEY (subject_id, user_id)
        REFERENCES subjects (id, user_id) ON DELETE CASCADE,
    CONSTRAINT chk_assignments_completed
        CHECK ((status = 'completed' AND completed_at IS NOT NULL)
            OR (status <> 'completed' AND completed_at IS NULL))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS study_sessions (
    id                INT UNSIGNED       NOT NULL AUTO_INCREMENT,
    user_id           INT UNSIGNED       NOT NULL,
    subject_id        INT UNSIGNED       NOT NULL,
    title             VARCHAR(150)       NOT NULL,
    notes             TEXT               NULL,
    session_date      DATE               NOT NULL,
    start_time        TIME               NOT NULL,
    duration_minutes  SMALLINT UNSIGNED  NOT NULL,
    is_completed      TINYINT(1)         NOT NULL DEFAULT 0,
    completed_at      TIMESTAMP          NULL DEFAULT NULL,
    created_at        TIMESTAMP          NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at        TIMESTAMP          NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    KEY idx_sessions_user_date (user_id, session_date),
    KEY idx_sessions_user_completed (user_id, is_completed, session_date),
    KEY idx_sessions_subject (subject_id, user_id),
    CONSTRAINT fk_sessions_user FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE,
    CONSTRAINT fk_sessions_subject FOREIGN KEY (subject_id, user_id)
        REFERENCES subjects (id, user_id) ON DELETE CASCADE,
    CONSTRAINT chk_sessions_duration CHECK (duration_minutes BETWEEN 5 AND 720),
    CONSTRAINT chk_sessions_completed
        CHECK ((is_completed = 1 AND completed_at IS NOT NULL)
            OR (is_completed = 0 AND completed_at IS NULL))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
