"""
race_demo.py - show the race condition, then the fix.   Run:  python race_demo.py
(Member 4's live demo: 10 students press "Book" for the same PC and time at once.)
"""
import os
import tempfile
import threading

os.environ["SMARTLAB_DB"] = os.path.join(tempfile.mkdtemp(), "demo.db")     # throw-away database

import booking  # noqa: E402
import db  # noqa: E402


def attempt(safe):
    db.execute("DELETE FROM bookings")
    results = []

    def student(user_id):
        try:
            booking.book(user_id, 1, "2026-11-01T10:00", "2026-11-01T11:00", safe=safe, think=0.05)
            results.append("booked")
        except booking.BookingError:
            results.append("refused")

    threads = [threading.Thread(target=student, args=(1 + i % 3,)) for i in range(10)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    return results.count("booked")


db.init_db()
db.execute("INSERT INTO computers(name, lab) VALUES ('PC-01', 'Demo Lab')")
print("WITHOUT lock and transaction: %d of 10 students got the SAME PC (double booking!)" % attempt(safe=False))
print("WITH mutex + transaction    : %d of 10 students got the PC (correct)" % attempt(safe=True))
