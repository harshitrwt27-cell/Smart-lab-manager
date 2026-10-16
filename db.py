"""
db.py - the DATABASE (plain SQL, SQLite).   Shared by everyone, but each table has an owner.

We use raw SQL on purpose: the DBMS evaluator wants to SEE the CREATE TABLE,
constraints, JOINs, views and triggers, and an ORM would hide all of that.
"""
import os
import sqlite3
from contextlib import closing

DB_PATH = os.getenv("SMARTLAB_DB", os.path.join(os.path.dirname(os.path.abspath(__file__)), "smartlab.db"))

SCHEMA = """
-- ===== Member 4 owns: users, computers, bookings, audit_log =====
CREATE TABLE IF NOT EXISTS users (
    id    INTEGER PRIMARY KEY,
    name  TEXT NOT NULL,
    role  TEXT NOT NULL DEFAULT 'student' CHECK (role IN ('student', 'admin'))
);
CREATE TABLE IF NOT EXISTS computers (
    id         INTEGER PRIMARY KEY,
    name       TEXT NOT NULL UNIQUE,                 -- hostname sent by the agent
    lab        TEXT NOT NULL,
    status     TEXT NOT NULL DEFAULT 'AVAILABLE' CHECK (status IN ('AVAILABLE', 'MAINTENANCE')),
    last_seen  REAL,                                 -- time of last heartbeat (epoch seconds)
    cpu        REAL,
    ram        REAL,
    procs      INTEGER,
    top_procs  TEXT                                  -- JSON list of the busiest processes
);
CREATE TABLE IF NOT EXISTS bookings (
    id           INTEGER PRIMARY KEY,
    user_id      INTEGER NOT NULL REFERENCES users(id),
    computer_id  INTEGER NOT NULL REFERENCES computers(id),
    start_time   TEXT NOT NULL,
    end_time     TEXT NOT NULL,
    status       TEXT NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE', 'CANCELLED')),
    CHECK (end_time > start_time)
);
CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY, what TEXT, at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TRIGGER IF NOT EXISTS trg_booking_insert AFTER INSERT ON bookings
BEGIN
    INSERT INTO audit_log(what) VALUES ('booking ' || NEW.id || ': user ' || NEW.user_id || ' booked computer ' || NEW.computer_id);
END;
CREATE TRIGGER IF NOT EXISTS trg_booking_cancel AFTER UPDATE OF status ON bookings
BEGIN
    INSERT INTO audit_log(what) VALUES ('booking ' || NEW.id || ': ' || OLD.status || ' -> ' || NEW.status);
END;
CREATE VIEW IF NOT EXISTS v_booking_details AS
    SELECT b.id, u.name AS student, c.name AS computer, c.lab, b.start_time, b.end_time, b.status
    FROM bookings b JOIN users u ON u.id = b.user_id JOIN computers c ON c.id = b.computer_id;

-- ===== Member 1 owns: syscall_log =====
CREATE TABLE IF NOT EXISTS syscall_log (
    id INTEGER PRIMARY KEY, call TEXT NOT NULL, args TEXT, status TEXT, ms REAL,
    at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE VIEW IF NOT EXISTS v_syscall_summary AS
    SELECT call, COUNT(*) AS times_called, ROUND(AVG(ms), 3) AS avg_ms,
           SUM(status = 'ERROR') AS errors
    FROM syscall_log GROUP BY call;

-- ===== Member 2 owns: task_log, metrics =====
CREATE TABLE IF NOT EXISTS task_log (
    id INTEGER PRIMARY KEY, pid INTEGER NOT NULL, program TEXT NOT NULL,
    user_id INTEGER REFERENCES users(id), computer_id INTEGER REFERENCES computers(id),
    started_at TEXT DEFAULT CURRENT_TIMESTAMP, ended_at TEXT, exit_code INTEGER
);
CREATE TABLE IF NOT EXISTS metrics (                 -- history: one row per computer every 15 s
    id INTEGER PRIMARY KEY, computer_id INTEGER NOT NULL REFERENCES computers(id),
    at REAL NOT NULL, cpu REAL, ram REAL
);
CREATE INDEX IF NOT EXISTS ix_metrics_computer_time ON metrics(computer_id, at);
CREATE VIEW IF NOT EXISTS v_user_tasks AS
    SELECT u.name AS student, COUNT(t.id) AS tasks_started, COUNT(t.ended_at) AS tasks_finished
    FROM users u LEFT JOIN task_log t ON t.user_id = u.id GROUP BY u.id, u.name;

-- ===== Member 3 owns: sched_runs, sched_results =====
CREATE TABLE IF NOT EXISTS sched_runs (
    id INTEGER PRIMARY KEY, algorithm TEXT NOT NULL, quantum INTEGER,
    avg_wait REAL, avg_turnaround REAL, at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS sched_results (
    run_id INTEGER NOT NULL REFERENCES sched_runs(id), pid TEXT NOT NULL,
    arrival INTEGER, burst INTEGER, finish INTEGER, waiting INTEGER, turnaround INTEGER,
    PRIMARY KEY (run_id, pid)
);
CREATE VIEW IF NOT EXISTS v_algorithm_compare AS
    SELECT algorithm, COUNT(*) AS runs, ROUND(AVG(avg_wait), 2) AS mean_wait,
           ROUND(AVG(avg_turnaround), 2) AS mean_turnaround
    FROM sched_runs GROUP BY algorithm;
"""


def connect():
    """One connection per call. isolation_level=None = autocommit, we write BEGIN ourselves when needed."""
    conn = sqlite3.connect(DB_PATH, timeout=10, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")      # SQLite ignores foreign keys unless you ask
    conn.execute("PRAGMA journal_mode = WAL")     # readers do not block the writer
    return conn


def query(sql, args=()):
    """SELECT -> list of dictionaries."""
    with closing(connect()) as conn:
        return [dict(row) for row in conn.execute(sql, args)]


def execute(sql, args=()):
    """INSERT / UPDATE / DELETE -> id of the new row."""
    with closing(connect()) as conn:
        return conn.execute(sql, args).lastrowid


def init_db():
    with closing(connect()) as conn:
        conn.executescript(SCHEMA)
        if conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
            conn.executemany("INSERT INTO users(name, role) VALUES (?, ?)",
                             [("Admin", "admin"), ("Riya Sharma", "student"), ("Aman Verma", "student")])
