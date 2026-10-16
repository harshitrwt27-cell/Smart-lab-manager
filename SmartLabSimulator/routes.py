import json
from datetime import datetime

from flask import Blueprint, jsonify, render_template, request
from sqlalchemy import func, text

import booking_service
import cpu_scheduling
import memory_management
import syscalls
import task_manager
from app import db
from models import Booking, Computer, TaskLog, User

main = Blueprint("main", __name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def get_system_summary():
    total_computers = Computer.query.count()
    available_computers = Computer.query.filter(func.lower(Computer.status) == "available").count()
    in_use_computers = Computer.query.filter(func.lower(Computer.status) == "in_use").count()
    maintenance_computers = Computer.query.filter(func.lower(Computer.status) == "maintenance").count()

    return {
        "total_computers": total_computers,
        "available_computers": available_computers,
        "in_use_computers": in_use_computers,
        "maintenance_computers": maintenance_computers,
    }


def error(message, code=400):
    return jsonify({"error": message}), code


def rows_of(sql):
    """Run a SELECT and return a list of dictionaries (used for views/reports)."""
    result = db.session.execute(text(sql))
    return [dict(row._mapping) for row in result]


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------
@main.route("/")
def home():
    return render_template("dashboard.html", summary=get_system_summary())


@main.route("/computers")
def computers():
    computers = Computer.query.order_by(Computer.id).all()
    return render_template("computer.html", computers=computers)


@main.route("/taskmanager")
def taskmanager_page():
    return render_template("taskmanager.html", programs=list(syscalls.PROGRAMS),
                           users=User.query.all(), computers=Computer.query.all())


@main.route("/reports")
def reports_page():
    return render_template("reports.html")


# ---------------------------------------------------------------------------
# Computers
# ---------------------------------------------------------------------------
@main.route("/api/system")
def api_system():
    return jsonify(get_system_summary())


@main.route("/api/computers")
def api_computers():
    computers = Computer.query.order_by(Computer.id).all()
    return jsonify([computer.to_dict() for computer in computers])


# ---------------------------------------------------------------------------
# OS: task manager
# ---------------------------------------------------------------------------
@main.route("/api/machine")
def api_machine():
    return jsonify(task_manager.machine_stats())


@main.route("/api/processes")
def api_processes():
    sort_by = request.args.get("sort", "cpu")
    limit = request.args.get("limit", 15, type=int)
    return jsonify(task_manager.system_processes(limit=limit, sort_by=sort_by))


@main.route("/api/tasks", methods=["GET"])
def api_tasks():
    tasks = task_manager.list_tasks()

    # Save the end time of tasks that have just finished (OS data -> DBMS).
    for task in tasks:
        if task["state"] == "TERMINATED":
            log = TaskLog.query.filter_by(pid=task["pid"], ended_at=None).first()
            if log:
                log.ended_at = datetime.utcnow()
                log.exit_code = task["exit_code"]
    db.session.commit()

    return jsonify({"tasks": tasks, "states": task_manager.state_summary(tasks)})


@main.route("/api/tasks", methods=["POST"])
def api_create_task():
    data = request.get_json(silent=True) or {}
    pcb, record = task_manager.create_task(
        program=data.get("program", ""),
        seconds=data.get("seconds", 30),
        user_id=data.get("user_id"),
        computer_id=data.get("computer_id"),
        priority=data.get("priority", "normal"),
    )
    if pcb is None:
        return error(record["result"]["error"])

    db.session.add(TaskLog(pid=pcb["pid"], program=pcb["name"], priority=pcb["priority"],
                           user_id=pcb["user_id"], computer_id=pcb["computer_id"]))
    db.session.commit()
    return jsonify(pcb), 201


@main.route("/api/tasks/<int:pid>/<action>", methods=["POST"])
def api_control_task(pid, action):
    if action not in ("kill", "suspend", "resume", "nice"):
        return error("action must be kill, suspend, resume or nice")
    data = request.get_json(silent=True) or {}
    record = task_manager.control_task(pid, action, data.get("level"))
    if record["status"] != "OK":
        return error(record["result"]["error"])
    return jsonify(record)


# ---------------------------------------------------------------------------
# OS: system calls
# ---------------------------------------------------------------------------
@main.route("/api/syscalls")
def api_syscall_table():
    """The syscall table: name, category and what the function does."""
    return jsonify([
        {"name": name, "category": category, "description": (function.__doc__ or "").strip().split("\n")[0]}
        for name, (function, category) in syscalls.SYSCALL_TABLE.items()
    ])


@main.route("/api/syscalls/trace")
def api_syscall_trace():
    return jsonify(syscalls.get_trace(limit=request.args.get("limit", 30, type=int)))


@main.route("/api/syscall", methods=["POST"])
def api_syscall():
    data = request.get_json(silent=True) or {}
    name = data.get("name", "")
    record = syscalls.invoke(name, data.get("args") or {})
    return jsonify(record), (200 if record["status"] == "OK" else 400)


# ---------------------------------------------------------------------------
# OS: scheduling and memory simulations
# ---------------------------------------------------------------------------
@main.route("/api/scheduling", methods=["POST"])
def api_scheduling():
    payload = request.get_json(silent=True) or {}
    processes = payload.get("processes", [])
    if not processes:
        return error("No process data provided.")

    algorithm = payload.get("algorithm", "fcfs")
    quantum = int(payload.get("quantum", 2))
    try:
        if algorithm == "all":
            return jsonify(cpu_scheduling.compare_all(processes, quantum))
        return jsonify(cpu_scheduling.schedule(processes, algorithm, quantum))
    except (ValueError, TypeError) as problem:
        return error(str(problem))


@main.route("/api/memory", methods=["POST"])
def api_memory():
    payload = request.get_json(silent=True) or {}
    blocks = payload.get("blocks", [])
    processes = payload.get("processes", [])
    if not blocks or not processes:
        return error("Provide both block sizes and process sizes.")
    try:
        return jsonify(memory_management.allocate(payload.get("strategy", "first"), blocks, processes))
    except (ValueError, TypeError) as problem:
        return error(str(problem))


@main.route("/api/paging", methods=["POST"])
def api_paging():
    payload = request.get_json(silent=True) or {}
    pages = payload.get("pages", [])
    if not pages:
        return error("Provide a page reference string.")
    try:
        return jsonify(memory_management.page_replacement(
            pages, int(payload.get("frames", 3)), payload.get("algorithm", "fifo")))
    except (ValueError, TypeError) as problem:
        return error(str(problem))


# ---------------------------------------------------------------------------
# DBMS: bookings (mutex + transaction) and reports (views)
# ---------------------------------------------------------------------------
@main.route("/api/bookings", methods=["GET"])
def api_bookings():
    return jsonify(rows_of("SELECT * FROM v_booking_details ORDER BY start_time"))


@main.route("/api/bookings", methods=["POST"])
def api_create_booking():
    data = request.get_json(silent=True) or {}
    try:
        booking = booking_service.create_booking(
            data.get("user_id"), data.get("computer_id"), data.get("start_time"), data.get("end_time"))
    except booking_service.BookingError as problem:
        return error(str(problem), 409)
    return jsonify(booking.to_dict()), 201


@main.route("/api/bookings/<int:booking_id>/cancel", methods=["POST"])
def api_cancel_booking(booking_id):
    try:
        return jsonify(booking_service.cancel_booking(booking_id).to_dict())
    except booking_service.BookingError as problem:
        return error(str(problem), 404)


@main.route("/api/reports/<name>")
def api_report(name):
    queries = {
        "syscalls": "SELECT * FROM v_syscall_summary ORDER BY calls DESC",
        "users": "SELECT * FROM v_user_task_usage ORDER BY tasks_started DESC",
        "computers": "SELECT * FROM v_computer_utilisation ORDER BY bookings DESC",
        "audit": "SELECT * FROM audit_log ORDER BY id DESC LIMIT 30",
        "tasks": ("SELECT t.pid, t.program, t.priority, u.name AS user_name, c.computer_name, "
                  "t.started_at, t.ended_at, t.exit_code "
                  "FROM task_log t LEFT JOIN users u ON u.id = t.user_id "
                  "LEFT JOIN computers c ON c.id = t.computer_id ORDER BY t.id DESC LIMIT 30"),
    }
    if name not in queries:
        return error("unknown report", 404)
    return jsonify(rows_of(queries[name]))
