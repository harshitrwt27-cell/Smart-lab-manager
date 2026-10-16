"""
agent.py - runs on EVERY lab computer and reports to the server (MEMBER 2).

    pip install psutil
    python agent.py --server http://SERVER-IP:5000 --lab "CS Lab 1" --key lab123

Sends every few seconds: CPU %, RAM %, number of processes, names of the 5 busiest
processes. Nothing else (no files, no screen, no keystrokes). It cannot be controlled remotely.
"""
import argparse
import json
import socket
import time
import urllib.error
import urllib.request

import psutil

cache = {}      # remember psutil.Process objects so cpu_percent() has a previous call to compare with


def top_processes(n=5):
    rows = []
    for p in psutil.process_iter(["pid", "name"]):
        try:
            proc = cache.setdefault(p.info["pid"], p)
            rows.append({"name": p.info["name"] or "?", "cpu": proc.cpu_percent(None) / psutil.cpu_count()})
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return sorted(rows, key=lambda r: -r["cpu"])[:n]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--server", required=True)
    ap.add_argument("--lab", default="Lab")
    ap.add_argument("--key", default="lab123")
    ap.add_argument("--interval", type=float, default=3)
    a = ap.parse_args()

    top_processes()                                   # first call only starts the counters
    time.sleep(1)
    wait = 2
    while True:
        data = {"hostname": socket.gethostname(), "lab": a.lab, "cpu": psutil.cpu_percent(None),
                "ram": psutil.virtual_memory().percent, "procs": len(psutil.pids()), "top": top_processes()}
        request = urllib.request.Request(a.server.rstrip("/") + "/api/agent/heartbeat",
                                         data=json.dumps(data).encode(),
                                         headers={"Content-Type": "application/json", "X-Lab-Key": a.key})
        try:
            urllib.request.urlopen(request, timeout=5).read()
            wait = 2
            time.sleep(a.interval)
        except urllib.error.HTTPError as e:
            print("server refused:", e.code)           # wrong key = 403
            time.sleep(a.interval)
        except OSError as e:
            print("cannot reach server (%s), retrying in %s s" % (e, wait))
            time.sleep(wait)
            wait = min(wait * 2, 60)                    # wait longer after each failure, max 60 s


if __name__ == "__main__":
    main()
