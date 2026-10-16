"""
cpu_scheduling.py  -  CPU scheduling algorithms
================================================

Each process is a dictionary:
    pid       name, e.g. "P1"
    burst     CPU time needed
    arrival   time it arrives (default 0)
    priority  smaller number = more important (default 0)

The simulator moves a clock forward ONE time unit at a time and, at each unit,
asks "which process gets the CPU now?". The algorithm only changes the answer.
"""

ALGORITHMS = ["fcfs", "sjf", "srtf", "priority", "rr"]


def _clean(processes):
    """Fill in missing fields and convert text to numbers."""
    cleaned = []
    for index, p in enumerate(processes):
        cleaned.append({
            "pid": p.get("pid") or "P" + str(index + 1),
            "burst": int(p.get("burst", 0)),
            "arrival": int(p.get("arrival", 0)),
            "priority": int(p.get("priority", 0)),
            "order": index,
        })
    return cleaned


def schedule(processes, algorithm="fcfs", quantum=2):
    """Run one algorithm and return per-process times, a Gantt chart and averages."""
    algorithm = algorithm.lower()
    if algorithm not in ALGORITHMS:
        raise ValueError("algorithm must be one of " + ", ".join(ALGORITHMS))
    procs = _clean(processes)
    if not procs:
        return {"algorithm": algorithm, "processes": [], "gantt": [],
                "average_waiting": 0, "average_turnaround": 0, "average_response": 0}
    if any(p["burst"] <= 0 for p in procs):
        raise ValueError("burst time must be at least 1")
    if algorithm == "rr" and quantum < 1:
        raise ValueError("quantum must be at least 1")

    # Processes sorted by arrival time (ties keep the order the user typed them).
    waiting_for_arrival = sorted(procs, key=lambda p: (p["arrival"], p["order"]))
    remaining = {p["pid"]: p["burst"] for p in procs}
    first_run, finish = {}, {}
    ready = []            # processes that have arrived and are not finished
    gantt = []            # list of [pid, start, end]
    clock = 0
    current = None        # process holding the CPU
    slice_used = 0        # how long 'current' has run (for round robin)

    def admit_arrivals():
        """Move every process whose arrival time has come into the ready list."""
        while waiting_for_arrival and waiting_for_arrival[0]["arrival"] <= clock:
            ready.append(waiting_for_arrival.pop(0))

    def pick():
        """The heart of every algorithm: choose who runs next."""
        if algorithm in ("fcfs", "rr"):
            return ready[0]
        if algorithm == "sjf":
            return min(ready, key=lambda p: (p["burst"], p["arrival"], p["order"]))
        if algorithm == "srtf":
            return min(ready, key=lambda p: (remaining[p["pid"]], p["arrival"], p["order"]))
        return min(ready, key=lambda p: (p["priority"], p["arrival"], p["order"]))  # priority

    while len(finish) < len(procs):
        admit_arrivals()
        if not ready:                       # CPU idle until the next arrival
            clock += 1
            continue

        if algorithm == "srtf":
            current = pick()                # preemptive: re-decide every time unit
        elif current is None:
            current = pick()                # the others keep the CPU until they must give it up

        pid = current["pid"]
        first_run.setdefault(pid, clock)

        # run for exactly one time unit
        if gantt and gantt[-1][0] == pid and gantt[-1][2] == clock:
            gantt[-1][2] += 1               # extend the previous bar
        else:
            gantt.append([pid, clock, clock + 1])
        remaining[pid] -= 1
        clock += 1
        slice_used += 1

        admit_arrivals()                    # new arrivals join BEFORE a preempted process re-queues

        if remaining[pid] == 0:             # finished
            finish[pid] = clock
            ready.remove(current)
            current, slice_used = None, 0
        elif algorithm == "rr" and slice_used == quantum:   # time slice over: go to the back
            ready.remove(current)
            ready.append(current)
            current, slice_used = None, 0

    rows, tw, tt, tr = [], 0, 0, 0
    for p in procs:
        pid = p["pid"]
        turnaround = finish[pid] - p["arrival"]          # time in the system
        waiting = turnaround - p["burst"]                # time spent not running
        response = first_run[pid] - p["arrival"]         # time until first CPU
        rows.append({"pid": pid, "arrival": p["arrival"], "burst": p["burst"],
                     "priority": p["priority"], "start": first_run[pid],
                     "completion": finish[pid], "turnaround": turnaround,
                     "waiting": waiting, "response": response})
        tw, tt, tr = tw + waiting, tt + turnaround, tr + response

    n = len(procs)
    return {"algorithm": algorithm, "processes": rows,
            "gantt": [{"pid": g[0], "start": g[1], "end": g[2]} for g in gantt],
            "average_waiting": round(tw / n, 2),
            "average_turnaround": round(tt / n, 2),
            "average_response": round(tr / n, 2)}


def fcfs(processes):
    """Kept so older code (and the old tests) still work."""
    return schedule(processes, "fcfs")


def compare_all(processes, quantum=2):
    """Run every algorithm on the same processes (great for a comparison table)."""
    return {name: schedule(processes, name, quantum) for name in ALGORITHMS}
