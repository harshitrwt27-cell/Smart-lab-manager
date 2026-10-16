import os
import tempfile
import threading
import time

import pytest

# Use a throw-away database so the tests never touch the real one.
_db_file = os.path.join(tempfile.mkdtemp(), "test.db")
os.environ["DATABASE_URL"] = "sqlite:///" + _db_file.replace("\\", "/")

from app import create_app, db  # noqa: E402
import syscalls  # noqa: E402
import task_manager  # noqa: E402


@pytest.fixture(scope="module")
def client():
    app = create_app()
    yield app.test_client()
    # stop any child processes left running
    for pid in syscalls.child_pids():
        syscalls.invoke("kill", {"pid": pid})


# ---------------------------------------------------------------- pages / API
def test_pages_load(client):
    for url in ["/", "/computers", "/taskmanager", "/reports"]:
        assert client.get(url).status_code == 200


def test_system_api_returns_summary(client):
    data = client.get("/api/system").get_json()
    assert data["total_computers"] == 4 and "in_use_computers" in data


# ---------------------------------------------------------------- scheduling
def test_scheduling_all_algorithms(client):
    procs = [{"pid": "P1", "burst": 5, "arrival": 0, "priority": 2},
             {"pid": "P2", "burst": 3, "arrival": 1, "priority": 1},
             {"pid": "P3", "burst": 8, "arrival": 2, "priority": 3}]
    for algo in ["fcfs", "sjf", "srtf", "priority", "rr"]:
        data = client.post("/api/scheduling", json={"processes": procs, "algorithm": algo}).get_json()
        assert len(data["processes"]) == 3 and data["gantt"]


def test_fcfs_respects_arrival_time(client):
    data = client.post("/api/scheduling", json={"processes": [
        {"pid": "A", "burst": 2, "arrival": 0}, {"pid": "B", "burst": 2, "arrival": 10}]}).get_json()
    assert data["average_waiting"] == 0           # B arrives after A is long finished


def test_bad_algorithm_is_rejected(client):
    r = client.post("/api/scheduling", json={"processes": [{"pid": "A", "burst": 1}], "algorithm": "nope"})
    assert r.status_code == 400


def test_memory_and_paging(client):
    mem = client.post("/api/memory", json={"strategy": "best", "blocks": [100, 500, 200, 300, 600],
                                           "processes": [212, 417, 112, 426]}).get_json()
    assert mem["allocation"] == [3, 1, 2, 4]
    pg = client.post("/api/paging", json={"algorithm": "lru", "frames": 3,
                                          "pages": [7, 0, 1, 2, 0, 3, 0, 4, 2, 3, 0, 3, 2]}).get_json()
    assert pg["page_faults"] == 9


# ---------------------------------------------------------------- system calls
def test_file_syscalls_round_trip():
    assert syscalls.invoke("write_file", {"name": "t.txt", "text": "abc"})["status"] == "OK"
    assert syscalls.invoke("read_file", {"name": "t.txt"})["result"]["content"] == "abc"
    assert syscalls.invoke("delete_file", {"name": "t.txt"})["status"] == "OK"


def test_file_syscall_through_web_api(client):
    r = client.post("/api/syscall", json={"name": "write_file", "args": {"name": "web.txt", "text": "hi"}})
    assert r.status_code == 200 and r.get_json()["result"]["bytes_written"] == 2
    syscalls.invoke("delete_file", {"name": "web.txt"})


def test_pipe_and_sysinfo_syscalls():
    assert syscalls.invoke("pipe", {"message": "ping"})["result"]["received"] == "ping"
    assert syscalls.invoke("sysinfo")["result"]["cpu_cores"] >= 1


def test_file_syscall_cannot_escape_sandbox():
    assert syscalls.invoke("read_file", {"name": "../../etc/passwd"})["status"] == "ERROR"


def test_unknown_syscall_returns_error(client):
    r = client.post("/api/syscall", json={"name": "format_disk"})
    assert r.status_code == 400


def test_syscalls_are_saved_in_database(client):
    client.post("/api/syscall", json={"name": "uname"})
    rows = client.get("/api/reports/syscalls").get_json()
    assert any(row["syscall"] == "uname" for row in rows)


# ---------------------------------------------------------------- task manager
def test_task_lifecycle(client):
    pcb = client.post("/api/tasks", json={"program": "editor-sim", "seconds": 30,
                                          "user_id": 2, "computer_id": 1}).get_json()
    pid = pcb["pid"]
    assert client.post(f"/api/tasks/{pid}/suspend").status_code == 200
    states = {t["pid"]: t["state"] for t in client.get("/api/tasks").get_json()["tasks"]}
    assert states[pid] == "SUSPENDED"
    assert client.post(f"/api/tasks/{pid}/resume").status_code == 200
    assert client.post(f"/api/tasks/{pid}/kill").status_code == 200
    states = {t["pid"]: t["state"] for t in client.get("/api/tasks").get_json()["tasks"]}
    assert states[pid] == "TERMINATED"
    # the DB remembers the finished task
    tasks = client.get("/api/reports/tasks").get_json()
    assert any(t["pid"] == pid and t["ended_at"] for t in tasks)


def test_cannot_kill_process_we_did_not_create(client):
    assert client.post("/api/tasks/%d/kill" % os.getpid()).status_code == 400


def test_unknown_program_is_rejected(client):
    assert client.post("/api/tasks", json={"program": "rm -rf /"}).status_code == 400


def test_busy_task_shows_cpu_usage(client):
    pcb = client.post("/api/tasks", json={"program": "compiler-sim", "seconds": 20}).get_json()
    time.sleep(0.8)
    client.get("/api/tasks")                      # first look primes the CPU counter
    time.sleep(1.0)
    task = [t for t in client.get("/api/tasks").get_json()["tasks"] if t["pid"] == pcb["pid"]][0]
    assert task["state"] == "RUNNING" and task["cpu"] > 1
    client.post(f"/api/tasks/{pcb['pid']}/kill")


# ---------------------------------------------------------------- bookings
def test_booking_rules(client):
    ok = {"user_id": 2, "computer_id": 1, "start_time": "2026-11-01T10:00", "end_time": "2026-11-01T12:00"}
    assert client.post("/api/bookings", json=ok).status_code == 201
    assert client.post("/api/bookings", json={**ok, "start_time": "2026-11-01T11:00",
                                              "end_time": "2026-11-01T13:00"}).status_code == 409   # overlap
    assert client.post("/api/bookings", json={**ok, "computer_id": 3}).status_code == 409           # maintenance
    assert client.post("/api/bookings", json={**ok, "end_time": "2026-11-01T09:00"}).status_code == 409
    audit = client.get("/api/reports/audit").get_json()
    assert any(a["action"] == "INSERT" for a in audit)                                                # trigger fired


def test_no_double_booking_under_race(client):
    """20 threads try to book the same slot at once: the mutex lets exactly one win."""
    app = client.application
    results = []

    def attempt(user):
        with app.app_context():
            import booking_service
            try:
                booking_service.create_booking(user, 4, "2026-12-01T10:00", "2026-12-01T11:00")
                results.append("ok")
            except booking_service.BookingError:
                results.append("refused")

    threads = [threading.Thread(target=attempt, args=(1 + i % 3,)) for i in range(20)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert results.count("ok") == 1 and results.count("refused") == 19
