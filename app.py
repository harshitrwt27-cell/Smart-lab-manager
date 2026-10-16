"""app.py - the web server. Only routing: every real job is done in the four modules."""
import os
import secrets
import sqlite3

from flask import Flask, jsonify, render_template, request

import booking
import db
import scheduler
import syscalls
import taskmgr

app = Flask(__name__)
LAB_KEY = os.getenv("LAB_KEY", "lab123")         # shared secret that agents send
db.init_db()


def bad(message, code=400):
    return jsonify({"error": message}), code


def _db_object_names():
    return {
        row["name"]
        for row in db.query(
            "SELECT name FROM sqlite_master "
            "WHERE type IN ('table', 'view') AND name NOT LIKE 'sqlite_%'"
        )
    }


def _quote_identifier(name):
    """Quote a SQLite identifier after it has been checked against sqlite_master."""
    return '"' + name.replace('"', '""') + '"'


@app.route("/")
def home():
    return render_template("index.html")


# ---------- Member 1: system calls ----------
@app.post("/api/syscall")
def api_syscall():
    data = request.get_json(silent=True) or {}
    record = syscalls.invoke(data.get("call", ""), data.get("args"))
    return jsonify(record), (200 if record["status"] == "OK" else 400)


@app.get("/api/syscalls")
def api_syscall_list():
    return jsonify({"calls": [{"name": n, "help": (f.__doc__ or "").strip()} for n, f in syscalls.TABLE.items()],
                    "trace": db.query("SELECT call, args, status, ms, at FROM syscall_log ORDER BY id DESC LIMIT 15")})


# ---------- Member 2: tasks + live computers ----------
@app.get("/api/tasks")
def api_tasks():
    return jsonify({"tasks": taskmgr.list_tasks(), "machine": taskmgr.machine_stats()})


@app.post("/api/tasks")
def api_create_task():
    d = request.get_json(silent=True) or {}
    entry, problem = taskmgr.create_task(d.get("program", ""), d.get("seconds", 30), d.get("user_id"), d.get("computer_id"))
    return (jsonify(entry), 201) if entry else bad(problem)


@app.post("/api/tasks/<int:pid>/<action>")
def api_task_action(pid, action):
    if action not in ("kill", "suspend", "resume"):
        return bad("action must be kill, suspend or resume")
    record = taskmgr.control(pid, action)
    return (jsonify(record), 200) if record["status"] == "OK" else bad(record["result"]["error"])


@app.post("/api/agent/heartbeat")
def api_heartbeat():
    if not secrets.compare_digest(request.headers.get("X-Lab-Key", ""), LAB_KEY):
        return bad("wrong key", 403)
    try:
        taskmgr.heartbeat(request.get_json(silent=True) or {})
    except (ValueError, TypeError) as problem:
        return bad(str(problem))
    return jsonify({"ok": True})


# ---------- Member 3: scheduling ----------
@app.post("/api/schedule")
def api_schedule():
    d = request.get_json(silent=True) or {}
    try:
        return jsonify(scheduler.run(d.get("algorithm", "fcfs"), d.get("processes", []), int(d.get("quantum", 2))))
    except (ValueError, KeyError, TypeError, sqlite3.IntegrityError) as problem:
        return bad(str(problem))


# ---------- Member 4: bookings ----------
@app.get("/api/computers")
def api_computers():
    taskmgr.local_heartbeat()
    return jsonify(booking.computers_with_state())


@app.get("/api/users")
def api_users():
    return jsonify(db.query("SELECT id, name FROM users ORDER BY id"))


@app.get("/api/bookings")
def api_bookings():
    return jsonify(db.query("SELECT * FROM v_booking_details ORDER BY start_time"))


@app.post("/api/bookings")
def api_book():
    d = request.get_json(silent=True) or {}
    try:
        return jsonify({"id": booking.book(d.get("user_id"), d.get("computer_id"), d.get("start"), d.get("end"))}), 201
    except booking.BookingError as problem:
        return bad(str(problem), 409)


@app.post("/api/bookings/<int:booking_id>/cancel")
def api_cancel(booking_id):
    try:
        booking.cancel(booking_id)
        return jsonify({"ok": True})
    except booking.BookingError as problem:
        return bad(str(problem), 404)


# ---------- reports (the views) ----------
REPORTS = {"syscalls": "SELECT * FROM v_syscall_summary", "tasks": "SELECT * FROM v_user_tasks",
           "algorithms": "SELECT * FROM v_algorithm_compare",
           "audit": "SELECT * FROM audit_log ORDER BY id DESC LIMIT 20"}


@app.get("/api/report/<name>")
def api_report(name):
    return jsonify(db.query(REPORTS[name])) if name in REPORTS else bad("unknown report", 404)


@app.get("/api/db/objects")
def api_db_objects():
    objects = []
    for name in sorted(_db_object_names()):
        quoted = _quote_identifier(name)
        count = db.query("SELECT COUNT(*) AS count FROM " + quoted)[0]["count"]
        kind = db.query("SELECT type FROM sqlite_master WHERE name = ?", (name,))[0]["type"]
        objects.append({"name": name, "type": kind, "rows": count})
    return jsonify(objects)


@app.get("/api/db/objects/<path:name>")
def api_db_object(name):
    if name not in _db_object_names():
        return bad("unknown database object", 404)
    quoted = _quote_identifier(name)
    columns = db.query("PRAGMA table_info(" + quoted + ")")
    rows = db.query("SELECT * FROM " + quoted + " LIMIT 25")
    return jsonify({"name": name, "columns": columns, "rows": rows})


if __name__ == "__main__":
    # HOST=0.0.0.0 lets other computers (the agents) reach the server.
    app.run(host=os.getenv("HOST", "127.0.0.1"), debug=os.getenv("DEBUG", "1") == "1")
