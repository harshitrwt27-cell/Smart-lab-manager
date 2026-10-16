"""
database_objects.py  -  DBMS features that SQLAlchemy models alone do not create
=================================================================================

  * VIEWS     : saved SELECT queries (JOINs and GROUP BY) used by the reports page
  * TRIGGERS  : code the database runs by itself when a row changes (audit trail)
  * SEED DATA : a few users so the lab can be demonstrated

Views and triggers are written in SQLite syntax. If you switch to MySQL
(see config.py) the syntax is slightly different, so we only create them on SQLite.
"""

from sqlalchemy import text
from werkzeug.security import generate_password_hash

from app import db

VIEWS_AND_TRIGGERS = [
    # ---- VIEW 1: JOIN of three tables --------------------------------------
    """
    CREATE VIEW IF NOT EXISTS v_booking_details AS
    SELECT b.id, u.name AS user_name, c.computer_name,
           b.start_time, b.end_time, b.status
    FROM bookings b
    JOIN users u     ON u.id = b.user_id
    JOIN computers c ON c.id = b.computer_id
    """,
    # ---- VIEW 2: GROUP BY over the OS system-call log ----------------------
    """
    CREATE VIEW IF NOT EXISTS v_syscall_summary AS
    SELECT syscall, category,
           COUNT(*)                                       AS calls,
           ROUND(AVG(duration_ms), 3)                     AS avg_ms,
           SUM(CASE WHEN status = 'ERROR' THEN 1 ELSE 0 END) AS errors
    FROM syscall_log
    GROUP BY syscall, category
    """,
    # ---- VIEW 3: LEFT JOIN, who started how many tasks ---------------------
    """
    CREATE VIEW IF NOT EXISTS v_user_task_usage AS
    SELECT u.id AS user_id, u.name AS user_name,
           COUNT(t.id) AS tasks_started,
           COUNT(t.ended_at) AS tasks_finished
    FROM users u
    LEFT JOIN task_log t ON t.user_id = u.id
    GROUP BY u.id, u.name
    """,
    # ---- VIEW 4: how busy each computer is ---------------------------------
    """
    CREATE VIEW IF NOT EXISTS v_computer_utilisation AS
    SELECT c.id AS computer_id, c.computer_name, c.status,
           COUNT(DISTINCT b.id) AS bookings,
           COUNT(DISTINCT t.id) AS tasks_run
    FROM computers c
    LEFT JOIN bookings b ON b.computer_id = c.id
    LEFT JOIN task_log t ON t.computer_id = c.id
    GROUP BY c.id, c.computer_name, c.status
    """,
    # ---- TRIGGERS: automatic audit trail -----------------------------------
    """
    CREATE TRIGGER IF NOT EXISTS trg_booking_insert
    AFTER INSERT ON bookings
    BEGIN
        INSERT INTO audit_log (table_name, action, row_id, detail, created_at)
        VALUES ('bookings', 'INSERT', NEW.id,
                'computer ' || NEW.computer_id || ' booked by user ' || NEW.user_id,
                datetime('now'));
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS trg_booking_status
    AFTER UPDATE OF status ON bookings
    BEGIN
        INSERT INTO audit_log (table_name, action, row_id, detail, created_at)
        VALUES ('bookings', 'UPDATE', NEW.id,
                'status ' || OLD.status || ' -> ' || NEW.status,
                datetime('now'));
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS trg_computer_status
    AFTER UPDATE OF status ON computers
    BEGIN
        INSERT INTO audit_log (table_name, action, row_id, detail, created_at)
        VALUES ('computers', 'UPDATE', NEW.id,
                NEW.computer_name || ': ' || OLD.status || ' -> ' || NEW.status,
                datetime('now'));
    END
    """,
]


def create_database_objects():
    """Create the views and triggers (only on SQLite)."""
    if db.engine.dialect.name != "sqlite":
        return
    for statement in VIEWS_AND_TRIGGERS:
        db.session.execute(text(statement))
    db.session.commit()


def seed_users():
    """Add demo users once. Passwords are stored as hashes, never as plain text."""
    from models import User

    if User.query.count() > 0:
        return
    db.session.add_all([
        User(name="Admin", email="admin@lab.edu", role="admin",
             password=generate_password_hash("admin123")),
        User(name="Riya Sharma", email="riya@lab.edu",
             password=generate_password_hash("student123")),
        User(name="Aman Verma", email="aman@lab.edu",
             password=generate_password_hash("student123")),
    ])
    db.session.commit()
