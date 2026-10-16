import os
import subprocess
import sys
import tempfile
import threading
import time

import pytest

os.environ["SMARTLAB_DB"] = os.path.join(tempfile.mkdtemp(), "test.db")     # never touch the real database
os.environ["LAB_KEY"] = "k"

import booking  # noqa: E402
import db  # noqa: E402
import scheduler  # noqa: E402
import syscalls  # noqa: E402
import taskmgr  # noqa: E402
from app import app  # noqa: E402

KEY = {"X-Lab-Key": "k"}


def beat(client, host, **extra):
    data = {"hostname": host, "lab": "Lab A", "cpu": 12, "ram": 40, "procs": 90, "top": [{"name": "python", "cpu": 5}]}
    data.update(extra)
    return client.post("/api/agent/heartbeat", json=data, headers=KEY)


@pytest.fixture(scope="module")
def client():
    c = app.test_client()
    for host in ["PC-01", "PC-02", "PC-03"]:
        assert beat(c, host).status_code == 200
    db.execute("UPDATE computers SET status = 'MAINTENANCE' WHERE name = 'PC-03'")
    yield c
    for pid in list(syscalls.children):
        syscalls.invoke("kill", {"pid": pid})


# ------------------------------------------------------------ Member 1: system calls
def test_file_calls_and_pipe():
    assert syscalls.invoke("write_file", {"name": "a.txt", "text": "hi"})["status"] == "OK"
    assert syscalls.invoke("read_file", {"name": "a.txt"})["result"]["content"] == "hi"
    assert syscalls.invoke("pipe", {"message": "ping"})["result"]["received"] == "ping"


def test_sandbox_blocks_path_escape():
    assert syscalls.invoke("read_file", {"name": "../../etc/passwd"})["status"] == "ERROR"


def test_unknown_call_and_unknown_program_fail_safely():
    assert syscalls.invoke("format_disk")["status"] == "ERROR"
    assert syscalls.invoke("spawn", {"program": "rm -rf /"})["status"] == "ERROR"


def test_every_call_is_saved_in_the_database():
    syscalls.invoke("getpid")
    rows = db.query("SELECT * FROM v_syscall_summary WHERE call = 'getpid'")
    assert rows and rows[0]["times_called"] >= 1


def test_cannot_kill_a_process_we_did_not_create():
    assert syscalls.invoke("kill", {"pid": os.getpid()})["status"] == "ERROR"


# ------------------------------------------------------------ Member 2: task manager + agents
def test_task_lifecycle_and_database(client):
    pid = client.post("/api/tasks", json={"program": "editor-sim", "seconds": 30, "user_id": 2}).get_json()["pid"]
    assert client.post(f"/api/tasks/{pid}/suspend").status_code == 200
    state = {t["pid"]: t["state"] for t in client.get("/api/tasks").get_json()["tasks"]}[pid]
    assert state == "SUSPENDED"
    client.post(f"/api/tasks/{pid}/resume")
    client.post(f"/api/tasks/{pid}/kill")
    state = {t["pid"]: t["state"] for t in client.get("/api/tasks").get_json()["tasks"]}[pid]
    assert state == "TERMINATED"
    assert db.query("SELECT ended_at FROM task_log WHERE pid = ?", (pid,))[0]["ended_at"] is not None


def test_busy_task_shows_cpu(client):
    pid = client.post("/api/tasks", json={"program": "compiler-sim", "seconds": 20, "user_id": 2}).get_json()["pid"]
    time.sleep(0.8)
    client.get("/api/tasks")
    time.sleep(1)
    task = [t for t in client.get("/api/tasks").get_json()["tasks"] if t["pid"] == pid][0]
    assert task["state"] == "RUNNING" and task["cpu"] > 1
    client.post(f"/api/tasks/{pid}/kill")


def test_foreign_key_stops_task_for_unknown_user(client):
    r = client.post("/api/tasks", json={"program": "editor-sim", "seconds": 5, "user_id": 999})
    assert r.status_code == 400


def test_agent_needs_key_and_clamps_numbers(client):
    assert client.post("/api/agent/heartbeat", json={"hostname": "X"}, headers={"X-Lab-Key": "bad"}).status_code == 403
    beat(client, "PC-CLAMP", cpu=9999, ram=-4)
    row = [c for c in client.get("/api/computers").get_json() if c["name"] == "PC-CLAMP"][0]
    assert row["cpu"] == 100 and row["ram"] == 0


def test_history_is_throttled(client):
    for _ in range(4):
        beat(client, "PC-HIST")
    cid = db.query("SELECT id FROM computers WHERE name = 'PC-HIST'")[0]["id"]
    assert db.query("SELECT COUNT(*) AS n FROM metrics WHERE computer_id = ?", (cid,))[0]["n"] == 1


def test_computer_states(client):
    states = {c["name"]: c["state"] for c in client.get("/api/computers").get_json()}
    assert states["PC-01"] == "AVAILABLE" and states["PC-03"] == "MAINTENANCE"
    db.execute("UPDATE computers SET last_seen = ? WHERE name = 'PC-02'", (time.time() - 60,))
    assert {c["name"]: c["state"] for c in client.get("/api/computers").get_json()}["PC-02"] == "OFFLINE"
    beat(client, "PC-02")


def test_computer_list_refresh_keeps_known_pcs_and_marks_this_laptop_available(client, monkeypatch):
    monkeypatch.setattr(taskmgr.socket, "gethostname", lambda: "LOCAL-LAPTOP")
    response = client.get("/api/computers")
    assert response.status_code == 200
    computers = {row["name"]: row for row in response.get_json()}
    assert computers["LOCAL-LAPTOP"]["state"] == "AVAILABLE"
    assert {"PC-01", "PC-02", "PC-03"}.issubset(computers)


def test_dbms_panel_lists_objects_and_limits_preview(client):
    objects = client.get("/api/db/objects")
    assert objects.status_code == 200
    names = {row["name"] for row in objects.get_json()}
    assert {"users", "computers", "v_booking_details"}.issubset(names)

    detail = client.get("/api/db/objects/users")
    assert detail.status_code == 200
    payload = detail.get_json()
    assert any(column["name"] == "name" for column in payload["columns"])
    assert len(payload["rows"]) <= 25

    assert client.get("/api/db/objects/does-not-exist").status_code == 404


# ------------------------------------------------------------ Member 3: scheduling (textbook answers)
TEXTBOOK = [{"pid": "P1", "burst": 24}, {"pid": "P2", "burst": 3}, {"pid": "P3", "burst": 3}]


def test_fcfs_textbook():
    assert scheduler.run("fcfs", TEXTBOOK)["avg_wait"] == 17.0


def test_sjf_textbook():
    assert scheduler.run("sjf", TEXTBOOK)["avg_wait"] == 3.0


def test_round_robin_textbook():
    r = scheduler.run("rr", TEXTBOOK, quantum=4)
    assert r["avg_wait"] == 5.67 and r["gantt"][0] == ["P1", 0, 4]


def test_scheduler_respects_arrival_and_idle():
    r = scheduler.run("fcfs", [{"pid": "A", "burst": 2, "arrival": 0}, {"pid": "B", "burst": 2, "arrival": 10}])
    assert r["avg_wait"] == 0 and r["gantt"][1] == ["B", 10, 12]


def test_scheduler_rejects_bad_input_and_saves_runs(client):
    assert client.post("/api/schedule", json={"algorithm": "magic", "processes": TEXTBOOK}).status_code == 400
    assert client.post("/api/schedule", json={"algorithm": "fcfs", "processes": [{"pid": "A", "burst": 0}]}).status_code == 400
    assert client.post("/api/schedule", json={"algorithm": "fcfs", "processes": [{"pid": "A", "burst": 1}, {"pid": "A", "burst": 1}]}).status_code == 400
    scheduler.run("fcfs", TEXTBOOK)
    assert db.query("SELECT runs FROM v_algorithm_compare WHERE algorithm = 'fcfs'")[0]["runs"] >= 1
    assert db.query("SELECT COUNT(*) AS n FROM sched_results")[0]["n"] > 0


def test_duplicate_pid_rolls_back_the_whole_run():
    before = db.query("SELECT COUNT(*) AS n FROM sched_runs")[0]["n"]
    with pytest.raises(Exception):
        scheduler.run("fcfs", [{"pid": "A", "burst": 2}, {"pid": "A", "burst": 3}])    # same pid twice breaks the primary key
    assert db.query("SELECT COUNT(*) AS n FROM sched_runs")[0]["n"] == before          # run row was undone too


# ------------------------------------------------------------ Member 4: bookings
def test_booking_rules(client):
    ok = {"user_id": 2, "computer_id": 1, "start": "2026-11-01T10:00", "end": "2026-11-01T12:00"}
    assert client.post("/api/bookings", json=ok).status_code == 201
    assert client.post("/api/bookings", json={**ok, "start": "2026-11-01T11:00", "end": "2026-11-01T13:00"}).status_code == 409
    assert client.post("/api/bookings", json={**ok, "start": "2026-11-01T12:00", "end": "2026-11-01T13:00"}).status_code == 201  # touching is fine
    assert client.post("/api/bookings", json={**ok, "computer_id": 3}).status_code == 409        # maintenance
    assert client.post("/api/bookings", json={**ok, "user_id": 99}).status_code == 409           # unknown user
    assert client.post("/api/bookings", json={**ok, "end": "2026-11-01T09:00"}).status_code == 409


def test_trigger_writes_audit_log_and_cancel(client):
    bid = client.post("/api/bookings", json={"user_id": 3, "computer_id": 2, "start": "2026-12-05T10:00", "end": "2026-12-05T11:00"}).get_json()["id"]
    assert client.post(f"/api/bookings/{bid}/cancel").status_code == 200
    audit = " ".join(r["what"] for r in db.query("SELECT what FROM audit_log"))
    assert "ACTIVE -> CANCELLED" in audit
    assert client.post(f"/api/bookings/{bid}/cancel").status_code == 404                          # cannot cancel twice


def test_database_itself_rejects_bad_rows():
    with pytest.raises(Exception):
        db.execute("INSERT INTO bookings(user_id, computer_id, start_time, end_time) VALUES (1, 1, '2026-01-02', '2026-01-01')")   # CHECK
    with pytest.raises(Exception):
        db.execute("INSERT INTO bookings(user_id, computer_id, start_time, end_time) VALUES (77, 1, '2026-01-01', '2026-01-02')")  # FOREIGN KEY


def _race(safe):
    db.execute("DELETE FROM bookings WHERE computer_id = 2")
    won = []

    def student(uid):
        try:
            booking.book(uid, 2, "2027-01-01T10:00", "2027-01-01T11:00", safe=safe, think=0.05)
            won.append(uid)
        except booking.BookingError:
            pass

    threads = [threading.Thread(target=student, args=(1 + i % 3,)) for i in range(10)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    return len(won)


def test_race_condition_exists_without_protection_and_is_fixed_with_it():
    assert _race(safe=False) > 1          # the bug is real
    assert _race(safe=True) == 1          # mutex + transaction fix it


# ------------------------------------------------------------ whole system: real agent process
def test_real_agent_reports_to_real_server():
    from werkzeug.serving import make_server
    server = make_server("127.0.0.1", 0, app, threaded=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    agent = subprocess.Popen([sys.executable, "agent.py", "--server", f"http://127.0.0.1:{server.server_port}",
                              "--lab", "E2E", "--key", "k", "--interval", "1"], stdout=subprocess.DEVNULL)
    try:
        found = None
        for _ in range(20):
            time.sleep(0.5)
            rows = [c for c in app.test_client().get("/api/computers").get_json() if c["lab"] == "E2E"]
            if rows and rows[0]["cpu"] is not None:
                found = rows[0]
                break
        assert found and found["state"] in ("AVAILABLE", "IN_USE") and found["procs"] > 0
    finally:
        agent.terminate()
        agent.wait(timeout=5)
        server.shutdown()
