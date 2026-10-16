"""
booking_service.py  -  where the OS and the DBMS meet
======================================================

Problem: two students press "Book PC-01" for the same time at the same moment.
Flask handles each click in its own THREAD, so both threads can run the
"is it free?" check before either one saves -> a RACE CONDITION and a double booking.

Fix (two layers, like real systems):
  1. OS side  : a MUTEX (threading.Lock) so only one thread is inside the
                critical section (check + insert) at a time.
  2. DBMS side: a TRANSACTION, so the insert is all-or-nothing (ACID).
"""

import threading
from datetime import datetime

from app import db
from models import Booking, Computer, User

booking_lock = threading.Lock()      # the mutex


class BookingError(Exception):
    """A booking was refused. The message says why."""


def _parse(value):
    """Accept '2026-10-12T10:00' (from the browser) or a datetime object."""
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        raise BookingError("time must look like 2026-10-12T10:00")


def create_booking(user_id, computer_id, start_time, end_time):
    start, end = _parse(start_time), _parse(end_time)
    if end <= start:
        raise BookingError("end time must be after start time")

    with booking_lock:                                   # ---- critical section starts
        if db.session.get(User, user_id) is None:
            raise BookingError("user does not exist")

        computer = db.session.get(Computer, computer_id)
        if computer is None:
            raise BookingError("computer does not exist")
        if computer.status == "MAINTENANCE":
            raise BookingError(computer.computer_name + " is under maintenance")

        # Overlap test: an existing booking clashes if it starts before we end
        # AND ends after we start.
        clash = Booking.query.filter(
            Booking.computer_id == computer_id,
            Booking.status == "ACTIVE",
            Booking.start_time < end,
            Booking.end_time > start,
        ).first()
        if clash:
            raise BookingError("already booked from %s to %s" % (clash.start_time, clash.end_time))

        booking = Booking(user_id=user_id, computer_id=computer_id,
                          start_time=start, end_time=end)
        try:
            db.session.add(booking)
            db.session.commit()                          # transaction COMMIT
        except Exception:
            db.session.rollback()                        # transaction ROLLBACK
            raise
        return booking                                   # ---- critical section ends


def cancel_booking(booking_id):
    booking = db.session.get(Booking, booking_id)
    if booking is None:
        raise BookingError("booking does not exist")
    booking.status = "CANCELLED"       # the trigger writes this change into audit_log
    db.session.commit()
    return booking
