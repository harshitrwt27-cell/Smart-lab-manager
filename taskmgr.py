"""
taskmgr.py - MEMBER 2 (OS: process control block, process states, live monitoring)
                      (DB: task_log, metrics history, foreign keys, LEFT JOIN view)

PCB = Process Control Block = the record the OS keeps for every process.
States: NEW -> READY -> RUNNING <-> WAITING, SUSPENDED (paused by user), TERMINATED.
"""
import json
import socket
import time

import psutil

import db
import syscalls

pcb = {}          # pid -> PCB dictionary (our process table)
watchers = {}     # pid -> psutil.Process. Kept because cpu_percent() compares with the LAST call.
_local_heartbeat_at = 0.0
_local_heartbeat_id = None
_local_heartbeat_name = None


def _watch(pid):
    if pid not in watchers:
        try:
            watchers[pid] = psutil.Process(pid)
            watchers[pid].cpu_percent(None)        # first call only starts the counter
        except psutil.NoSuchProcess:
            return None
    return watchers[pid]


def create_task(program, seconds, user_id, computer_id):
    """Start a process through the spawn system call and register its PCB."""
    record = syscalls.invoke("spawn", {"program": program, "seconds": seconds})
    if record["status"] != "OK":
        return None, record["result"]["error"]
    pid = record["result"]["pid"]
    try:
        log_id = db.execute("INSERT INTO task_log(pid, program, user_id, computer_id) VALUES (?,?,?,?)",
                            (pid, program, user_id, computer_id))
    except Exception as error:                      # e.g. a user id that does not exist (foreign key)
        syscalls.invoke("kill", {"pid": pid})
        return None, "database refused the task: " + str(error)
    pcb[pid] = {"pid": pid, "program": program, "state": "NEW", "log_id": log_id,
                "created": time.time(), "suspended": False, "exit_code": None}
    return pcb[pid], None


def _state(entry, process):
    exit_code = syscalls.children[entry["pid"]].poll()
    if exit_code is not None:
        entry["exit_code"] = exit_code
        return "TERMINATED", 0.0
    if entry["suspended"]:
        return "SUSPENDED", 0.0
    cpu = process.cpu_percent(None) if process else 0.0
    if entry["state"] == "NEW":
        return "READY", cpu                         # just created, waiting for the CPU
    return ("RUNNING" if cpu > 1 else "WAITING"), cpu


def list_tasks():
    rows = []
    for pid, entry in list(pcb.items()):
        process = _watch(pid)
        was = entry["state"]
        entry["state"], cpu = _state(entry, process)
        if entry["state"] == "TERMINATED" and was != "TERMINATED":      # just finished: update the database
            db.execute("UPDATE task_log SET ended_at = CURRENT_TIMESTAMP, exit_code = ? WHERE id = ?",
                       (entry["exit_code"], entry["log_id"]))
        mem = 0
        if entry["state"] != "TERMINATED" and process:
            try:
                mem = round(process.memory_info().rss / 1048576, 1)
            except psutil.Error:
                pass
        rows.append({**entry, "cpu": round(cpu, 1), "memory_mb": mem,
                     "runtime": round(time.time() - entry["created"])})
    return sorted(rows, key=lambda r: -r["created"])


def control(pid, action):
    """kill / suspend / resume, always through the system-call layer."""
    record = syscalls.invoke(action, {"pid": pid})
    entry = pcb.get(int(pid))
    if entry and record["status"] == "OK":
        entry["suspended"] = {"suspend": True, "resume": False}.get(action, entry["suspended"])
        if action == "kill":
            entry["exit_code"] = record["result"]["exit_code"]
    return record


def machine_stats():
    """This computer, right now."""
    mem = psutil.virtual_memory()
    return {"cpu": psutil.cpu_percent(None), "ram_percent": mem.percent,
            "ram_used_mb": mem.used // 1048576, "ram_total_mb": mem.total // 1048576,
            "processes": len(psutil.pids())}


# ---------------- real lab computers: heartbeats sent by agent.py ----------------
def heartbeat(data):
    """Save what a lab computer reports. First heartbeat registers the computer."""
    name = str(data.get("hostname", "")).strip()[:50]
    if not name:
        raise ValueError("hostname is required")
    num = lambda v: max(0.0, min(100.0, float(v)))              # never trust the agent's numbers
    cpu, ram = num(data.get("cpu", 0)), num(data.get("ram", 0))
    procs = int(data.get("procs", 0))
    top = [{"name": str(p.get("name", "?"))[:40], "cpu": num(p.get("cpu", 0))}
           for p in (data.get("top") or [])[:5] if isinstance(p, dict)]
    now = time.time()

    row = db.query("SELECT id FROM computers WHERE name = ?", (name,))
    if not row:
        db.execute("INSERT INTO computers(name, lab) VALUES (?, ?)", (name, str(data.get("lab", "Lab"))[:50]))
        row = db.query("SELECT id FROM computers WHERE name = ?", (name,))
    cid = row[0]["id"]
    db.execute("UPDATE computers SET lab=?, last_seen=?, cpu=?, ram=?, procs=?, top_procs=? WHERE id=?",
               (str(data.get("lab", "Lab"))[:50], now, cpu, ram, procs, json.dumps(top), cid))
    last = db.query("SELECT MAX(at) AS t FROM metrics WHERE computer_id = ?", (cid,))[0]["t"]
    if last is None or now - last >= 15:                         # history row every 15 s, not every 3 s
        db.execute("INSERT INTO metrics(computer_id, at, cpu, ram) VALUES (?,?,?,?)", (cid, now, cpu, ram))
        db.execute("DELETE FROM metrics WHERE computer_id = ? AND at < ?", (cid, now - 86400))   # keep 24 h
    return cid


def local_heartbeat():
    """Report this server's laptop without requiring a separate agent process."""
    global _local_heartbeat_at, _local_heartbeat_id, _local_heartbeat_name
    now = time.time()
    hostname = socket.gethostname()
    if (_local_heartbeat_id is not None and _local_heartbeat_name == hostname
            and now - _local_heartbeat_at < 2):
        return _local_heartbeat_id
    existing = db.query("SELECT id, lab, last_seen FROM computers WHERE name = ?", (hostname,))
    if (existing and existing[0]["lab"] != "This laptop"
            and existing[0]["last_seen"] is not None
            and now - existing[0]["last_seen"] <= 20):
        _local_heartbeat_id = existing[0]["id"]
        _local_heartbeat_at = now
        _local_heartbeat_name = hostname
        return _local_heartbeat_id
    top = []
    for process in psutil.process_iter(["name", "cpu_percent"]):
        try:
            top.append({"name": process.info["name"] or "?", "cpu": process.cpu_percent(None) / psutil.cpu_count()})
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    top.sort(key=lambda row: -row["cpu"])
    _local_heartbeat_id = heartbeat({
        "hostname": hostname,
        "lab": "This laptop",
        "cpu": psutil.cpu_percent(None),
        "ram": psutil.virtual_memory().percent,
        "procs": len(psutil.pids()),
        "top": top[:5],
    })
    _local_heartbeat_at = now
    _local_heartbeat_name = hostname
    return _local_heartbeat_id
