"""
scheduler.py - MEMBER 3 (OS: CPU scheduling FCFS / SJF / Round Robin, Gantt chart)
                        (DB: stores every run + per-process results, GROUP BY comparison)

A process is a dictionary: {"pid": "P1", "arrival": 0, "burst": 5}
Every algorithm returns the Gantt chart as a list of [pid, start, end].
Then the same code works out the times:
    turnaround = finish - arrival        waiting = turnaround - burst
"""
from contextlib import closing

import db


def fcfs(procs):
    """First Come First Served: run in order of arrival, each to the end."""
    t, gantt, finish = 0, [], {}
    for p in sorted(procs, key=lambda p: p["arrival"]):
        t = max(t, p["arrival"])                  # CPU may sit idle until the process arrives
        gantt.append([p["pid"], t, t + p["burst"]])
        t += p["burst"]
        finish[p["pid"]] = t
    return gantt, finish


def sjf(procs):
    """Shortest Job First (non-preemptive): of the processes that have arrived, run the shortest."""
    waiting = sorted(procs, key=lambda p: p["arrival"])
    t, gantt, finish = 0, [], {}
    while waiting:
        ready = [p for p in waiting if p["arrival"] <= t]
        if not ready:
            t = waiting[0]["arrival"]             # idle until the next arrival
            continue
        p = min(ready, key=lambda p: p["burst"])
        waiting.remove(p)
        gantt.append([p["pid"], t, t + p["burst"]])
        t += p["burst"]
        finish[p["pid"]] = t
    return gantt, finish


def round_robin(procs, quantum):
    """Round Robin: each process gets at most `quantum` time units, then goes to the back."""
    incoming = sorted(procs, key=lambda p: p["arrival"])
    left = {p["pid"]: p["burst"] for p in procs}
    queue, gantt, finish, t = [], [], {}, 0

    def admit():                                  # move arrived processes into the queue
        while incoming and incoming[0]["arrival"] <= t:
            queue.append(incoming.pop(0))

    while len(finish) < len(procs):
        admit()
        if not queue:
            t = incoming[0]["arrival"]
            continue
        p = queue.pop(0)
        run = min(quantum, left[p["pid"]])
        gantt.append([p["pid"], t, t + run])
        t += run
        left[p["pid"]] -= run
        admit()                                   # newcomers go BEFORE the process that was just preempted
        if left[p["pid"]] > 0:
            queue.append(p)
        else:
            finish[p["pid"]] = t
    return gantt, finish


def run(algorithm, procs, quantum=2):
    procs = [{"pid": str(p["pid"]), "arrival": int(p.get("arrival", 0)), "burst": int(p["burst"])} for p in procs]
    if not procs or any(p["burst"] < 1 for p in procs):
        raise ValueError("give at least one process, each with burst >= 1")
    if algorithm == "fcfs":
        gantt, finish = fcfs(procs)
    elif algorithm == "sjf":
        gantt, finish = sjf(procs)
    elif algorithm == "rr":
        if quantum < 1:
            raise ValueError("quantum must be at least 1")
        gantt, finish = round_robin(procs, quantum)
    else:
        raise ValueError("algorithm must be fcfs, sjf or rr")

    rows = []
    for p in procs:
        turnaround = finish[p["pid"]] - p["arrival"]
        rows.append({**p, "finish": finish[p["pid"]], "turnaround": turnaround, "waiting": turnaround - p["burst"]})
    avg_wait = round(sum(r["waiting"] for r in rows) / len(rows), 2)
    avg_tat = round(sum(r["turnaround"] for r in rows) / len(rows), 2)

    # One transaction: the run and ALL its result rows are saved together or not at all.
    with closing(db.connect()) as conn:
        conn.execute("BEGIN")
        try:
            run_id = conn.execute("INSERT INTO sched_runs(algorithm, quantum, avg_wait, avg_turnaround) VALUES (?,?,?,?)",
                                  (algorithm, quantum if algorithm == "rr" else None, avg_wait, avg_tat)).lastrowid
            conn.executemany("INSERT INTO sched_results VALUES (?,?,?,?,?,?,?)",
                             [(run_id, r["pid"], r["arrival"], r["burst"], r["finish"], r["waiting"], r["turnaround"]) for r in rows])
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
    return {"run_id": run_id, "algorithm": algorithm, "gantt": gantt, "processes": rows,
            "avg_wait": avg_wait, "avg_turnaround": avg_tat}
