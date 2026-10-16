"""
booking.py - MEMBER 4 (OS: race condition, mutex / critical section)
                      (DB: constraints, transaction COMMIT/ROLLBACK, trigger, JOIN, CASE + EXISTS)

PROBLEM  Two students book the same PC for the same time at the same moment.
         Each request runs in its own thread:   check "is it free?"  ->  insert.
         If both threads finish the check before either inserts, BOTH succeed = double booking.
FIX      OS side  : a mutex (threading.Lock), only one thread inside the critical section.
         DBMS side: a transaction (BEGIN IMMEDIATE ... COMMIT / ROLLBACK), all-or-nothing,
                    and it also protects when there are several server processes (a mutex cannot).
"""
import threading
import time
from contextlib import closing
from datetime import datetime

import db

lock = threading.Lock()          # the mutex


class BookingError(Exception):
    pass


def _clean(value):
    """'2026-11-01T10:00' -> '2026-11-01 10:00:00' (same format everywhere so text comparison works)."""
    try:
        return datetime.fromisoformat(value).strftime("%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError):
        raise BookingError("time must look like 2026-11-01T10:00")


def _check_and_insert(conn, user_id, computer_id, start, end, think):
    if not conn.execute("SELECT 1 FROM users WHERE id = ?", (user_id,)).fetchone():
        raise BookingError("user does not exist")
    computer = conn.execute("SELECT status FROM computers WHERE id = ?", (computer_id,)).fetchone()
    if computer is None:
        raise BookingError("computer does not exist")
    if computer["status"] == "MAINTENANCE":
        raise BookingError("computer is under maintenance")
    # Two time ranges overlap when each one starts before the other ends.
    clash = conn.execute("""SELECT start_time, end_time FROM bookings
                            WHERE computer_id = ? AND status = 'ACTIVE' AND start_time < ? AND end_time > ?""",
                         (computer_id, end, start)).fetchone()
    if clash:
        raise BookingError("already booked %s to %s" % (clash["start_time"], clash["end_time"]))
    time.sleep(think)            # ONLY for the race demo: makes the gap between check and insert wider
    return conn.execute("INSERT INTO bookings(user_id, computer_id, start_time, end_time) VALUES (?,?,?,?)",
                        (user_id, computer_id, start, end)).lastrowid


def book(user_id, computer_id, start_time, end_time, safe=True, think=0):
    start, end = _clean(start_time), _clean(end_time)
    if end <= start:
        raise BookingError("end time must be after start time")
    conn = db.connect()
    try:
        if not safe:                                  # the BUGGY version (used to demonstrate the problem)
            return _check_and_insert(conn, user_id, computer_id, start, end, think)
        with lock:                                    # critical section starts: one thread at a time
            conn.execute("BEGIN IMMEDIATE")           # start a transaction and take the write lock
            try:
                booking_id = _check_and_insert(conn, user_id, computer_id, start, end, think)
                conn.execute("COMMIT")
                return booking_id
            except Exception:
                conn.execute("ROLLBACK")              # undo everything if anything failed
                raise
    finally:
        conn.close()


def cancel(booking_id):
    with closing(db.connect()) as conn:
        done = conn.execute("UPDATE bookings SET status = 'CANCELLED' WHERE id = ? AND status = 'ACTIVE'",
                            (booking_id,)).rowcount
    if not done:
        raise BookingError("no active booking with that id")


def computers_with_state():
    """What the live page shows. The state is WORKED OUT from facts, never typed in by hand."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return db.query("""
        SELECT c.id, c.name, c.lab, c.cpu, c.ram, c.procs, c.top_procs,
               CASE WHEN c.last_seen IS NOT NULL THEN CAST(? - c.last_seen AS INTEGER) END AS seen_seconds_ago,
               CASE
                 WHEN c.status = 'MAINTENANCE' THEN 'MAINTENANCE'
                 WHEN c.last_seen IS NULL OR ? - c.last_seen > 20 THEN 'OFFLINE'
                 WHEN EXISTS (SELECT 1 FROM bookings b WHERE b.computer_id = c.id AND b.status = 'ACTIVE'
                              AND b.start_time <= ? AND b.end_time > ?) THEN 'IN_USE'
                 ELSE 'AVAILABLE'
               END AS state
        FROM computers c ORDER BY c.lab, c.name""", (time.time(), time.time(), now, now))
