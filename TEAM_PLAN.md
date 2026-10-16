# Team plan - every member owns ONE module that has an OS half and a DBMS half
(Two evaluators grade separately, so each of you must be able to face BOTH.)

| | Member 1 | Member 2 | Member 3 | Member 4 |
|---|---|---|---|---|
| Module | syscalls.py | taskmgr.py + agent.py | scheduler.py | booking.py + race_demo.py |
| OS topic | system calls, fork/exec/wait, file descriptors, pipe | PCB, process states, live CPU/RAM, zombie | FCFS, SJF, Round Robin, Gantt, waiting/turnaround | race condition, critical section, mutex |
| DBMS topic | syscall_log, GROUP BY view, db.py connection (WAL, foreign keys) | task_log + metrics, FOREIGN KEY, INDEX, retention, LEFT JOIN view | sched_runs 1:N sched_results, composite PK, ONE TRANSACTION, AVG view | users/computers/bookings, CHECK, UNIQUE, TRANSACTION, TRIGGER, JOIN, CASE+EXISTS |
| 60-second demo | invoke spawn -> row appears in trace -> report shows counts | start a task, suspend, kill -> states change, task_log gets ended_at | run same processes in all 3 algorithms, compare averages | race_demo.py: 10 of 10 double-book, then exactly 1 |
| Write from scratch on a whiteboard | sys_write_file (open/write/close) | state decision (_state) | round_robin() | the overlap query + book() with lock |

## Viva questions you WILL get
Member 1: What is a system call and why not call hardware directly? What does fork return in parent and child? Why must we wait() after kill? Why is the sandbox needed?
Member 2: What is in a PCB? Draw the 5-state diagram and say which of our states maps to which. Why does cpu_percent show 0 on the first call? Why is history saved every 15 s and not every 3 s?
Member 3: Which algorithm gives the lowest average waiting time and why (SJF)? What is the convoy effect? What happens to Round Robin if the quantum is huge / tiny? Why are the run row and result rows in one transaction?
Member 4: What is a race condition? Why does a mutex not help with two server processes (the DB transaction does)? What do ACID's A and I mean here? What does the trigger do and when does it fire?

## Whole team must be able to explain
The three diagrams in README.md, why state is computed (heartbeat age + bookings) and not typed in, and what is NOT built yet (phase 3 below).

## Not in this 40% on purpose (phase 3)
Memory allocation (first/best/worst fit) and page replacement, SRTF/priority, login and roles, job queue that runs student jobs on real machines, alerts, HTTPS + per-machine tokens.
