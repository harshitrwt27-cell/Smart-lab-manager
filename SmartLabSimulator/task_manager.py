"""
task_manager.py  -  the Task Manager of the Smart Lab Simulator
================================================================

Two jobs:
  1. LAB TASKS   : programs that students start through the spawn() system call.
                   We keep a Process Control Block (PCB) for each one.
  2. ALL PROCESSES: a look at every process on the machine, like Windows Task Manager.

PCB = the record an OS keeps for every process (pid, state, priority, owner ...).
"""

import time

import psutil

import syscalls

# ---------------------------------------------------------------------------
# Process states (the 5-state model taught in OS class)
#   NEW        - just created
#   READY      - waiting for the CPU
#   RUNNING    - using the CPU right now
#   WAITING    - blocked (sleeping, waiting for I/O or a timer)
#   SUSPENDED  - paused by the user (suspend system call)
#   TERMINATED - finished or killed
# ---------------------------------------------------------------------------

# pid -> PCB dictionary. This is our "process table".
PCB_TABLE = {}

# psutil.Process objects are cached because cpu_percent() measures the change
# since the LAST call. A brand-new Process object always reports 0.0.
_process_cache = {}


def _get_process(pid):
    """Return a cached psutil.Process object (or None if the process is gone)."""
    try:
        if pid not in _process_cache:
            process = psutil.Process(pid)
            process.cpu_percent(None)          # first call only "primes" the counter
            _process_cache[pid] = process
        return _process_cache[pid]
    except psutil.NoSuchProcess:
        _process_cache.pop(pid, None)
        return None


# ===========================================================================
# LAB TASKS (processes created by the simulator)
# ===========================================================================
def create_task(program, seconds=30, user_id=None, computer_id=None, priority="normal"):
    """Create a process using the spawn system call and register its PCB."""
    record = syscalls.invoke("spawn", {"program": program, "seconds": seconds})
    if record["status"] != "OK":
        return None, record

    pid = record["result"]["pid"]
    PCB_TABLE[pid] = {
        "pid": pid,
        "ppid": record["result"]["ppid"],
        "name": program,
        "priority": "normal",
        "user_id": user_id,
        "computer_id": computer_id,
        "created": time.time(),
        "state": "NEW",
        "suspended": False,
        "exit_code": None,
    }

    if priority != "normal":
        syscalls.invoke("nice", {"pid": pid, "level": priority})
        PCB_TABLE[pid]["priority"] = priority
    return PCB_TABLE[pid], record


def _work_out_state(pcb, process):
    """Decide which of the 5 states a lab task is in right now."""
    exit_code = syscalls.child_exit_code(pcb["pid"])
    if exit_code is not None:
        pcb["exit_code"] = exit_code
        return "TERMINATED", 0.0

    if process is None:
        return "TERMINATED", 0.0

    if pcb["suspended"]:
        return "SUSPENDED", 0.0

    cpu = process.cpu_percent(None)
    if pcb["state"] == "NEW":
        return "READY", cpu             # first time we look at it: it is waiting for the CPU
    return ("RUNNING" if cpu > 1.0 else "WAITING"), cpu


def list_tasks():
    """Refresh and return every PCB (lab tasks), newest first."""
    tasks = []
    for pid, pcb in list(PCB_TABLE.items()):
        process = _get_process(pid)
        state, cpu = _work_out_state(pcb, process)
        pcb["state"] = state

        memory_mb = threads = 0
        if process is not None and state != "TERMINATED":
            try:
                memory_mb = round(process.memory_info().rss / (1024 * 1024), 1)
                threads = process.num_threads()
            except psutil.Error:
                pass

        tasks.append({
            **pcb,
            "cpu": round(cpu, 1),
            "memory_mb": memory_mb,
            "threads": threads,
            "runtime_s": round(time.time() - pcb["created"], 1),
        })
    return sorted(tasks, key=lambda t: t["created"], reverse=True)


def control_task(pid, action, level=None):
    """Run kill / suspend / resume / nice on a lab task through the system-call layer."""
    arguments = {"pid": pid}
    if action == "nice":
        arguments["level"] = level

    record = syscalls.invoke(action, arguments)
    pcb = PCB_TABLE.get(int(pid))
    if pcb is not None and record["status"] == "OK":
        if action == "suspend":
            pcb["suspended"] = True
        elif action == "resume":
            pcb["suspended"] = False
        elif action == "nice":
            pcb["priority"] = level
        elif action == "kill":
            pcb["state"] = "TERMINATED"
            pcb["exit_code"] = record["result"]["exit_code"]
    return record


def state_summary(tasks):
    """Count how many tasks are in each state (used for the dashboard counters)."""
    counts = {s: 0 for s in ["NEW", "READY", "RUNNING", "WAITING", "SUSPENDED", "TERMINATED"]}
    for task in tasks:
        counts[task["state"]] += 1
    return counts


# ===========================================================================
# ALL PROCESSES ON THE MACHINE (read-only, like the Processes tab)
# ===========================================================================
def system_processes(limit=15, sort_by="cpu"):
    """Top processes of the whole machine. sort_by is 'cpu' or 'memory'."""
    rows = []
    for process in psutil.process_iter(["pid", "name", "memory_percent", "num_threads", "status"]):
        try:
            cached = _get_process(process.info["pid"])
            cpu = cached.cpu_percent(None) if cached else 0.0
            rows.append({
                "pid": process.info["pid"],
                "name": process.info["name"] or "?",
                "cpu": round(cpu, 1),
                "memory": round(process.info["memory_percent"] or 0, 2),
                "threads": process.info["num_threads"] or 0,
                "status": process.info["status"],
            })
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    key = "memory" if sort_by == "memory" else "cpu"
    rows.sort(key=lambda r: r[key], reverse=True)

    # Forget cache entries for processes that no longer exist so it cannot grow forever.
    alive = {r["pid"] for r in rows}
    for pid in list(_process_cache):
        if pid not in alive:
            _process_cache.pop(pid, None)
    return rows[:limit]


def machine_stats():
    """Numbers for the top of the task manager: CPU, RAM, process count."""
    memory = psutil.virtual_memory()
    return {
        "cpu_percent": psutil.cpu_percent(interval=None),
        "ram_percent": memory.percent,
        "ram_used_mb": memory.used // (1024 * 1024),
        "ram_total_mb": memory.total // (1024 * 1024),
        "process_count": len(psutil.pids()),
        "cpu_cores": psutil.cpu_count(),
    }
