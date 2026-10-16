# Smart Lab Simulator - what changed and how to run it

## Run
    pip install -r requirements.txt
    python run.py            # open http://127.0.0.1:5000
    pytest                   # 18 tests
(Delete `instance/resource_manager.db` if you have an old copy; a new one with the new tables is created on start.)

## Architecture (the idea to explain to both evaluators)
    Browser  ->  Flask routes  ->  task_manager.py  ->  syscalls.invoke()  ->  real OS (psutil / os / subprocess)
                                                              |
                                                       syscall_log table (DBMS)
    Bookings ->  booking_service.py  ->  mutex (OS)  +  transaction (DBMS)  ->  bookings table -> trigger -> audit_log

## OS part
| File | What it shows |
|---|---|
| syscalls.py | System call table + single `invoke()` entry point. 16 calls: getpid, getppid, spawn, kill, suspend, resume, wait, nice, write_file, read_file, stat, list_dir, delete_file, uname, sysinfo, pipe. Every call is timed, traced and saved to the DB. Files are sandboxed to `lab_files/`. |
| task_manager.py | Process table (PCB), 5-state model (NEW/READY/RUNNING/WAITING/SUSPENDED/TERMINATED), suspend/resume/kill/priority, machine-wide process list. |
| cpu_scheduling.py | FCFS, SJF, SRTF, Priority, Round Robin with arrival times, Gantt chart, waiting/turnaround/response. |
| memory_management.py | First/Best/Worst fit, page replacement FIFO/LRU/Optimal. |
| c_syscalls/syscall_demo.c | Real fork + exec + wait + pipe in C (Linux/WSL). |

## DBMS part
| File | What it shows |
|---|---|
| models.py | users, computers, bookings (CHECK + NOT NULL + FK), task_log, syscall_log, audit_log, indexes. |
| database_objects.py | 4 views (JOIN, LEFT JOIN, GROUP BY, aggregates), 3 triggers, hashed demo passwords. |
| booking_service.py | Overlap check + transaction (commit/rollback) protected by a mutex. Test fires 20 threads at one slot; exactly 1 wins. |
| /reports page | All views and the trigger-filled audit log. |

## Bugs fixed in the original
* FCFS ignored arrival time (waiting time was wrong whenever arrival > 0).
* Process list showed 0 % CPU for everything (psutil needs a primed counter).
* `/api/memory` returned the original blocks as "remaining_blocks".
* Process names were inserted into HTML without escaping.
* `users`/`bookings` tables existed but nothing used them.
