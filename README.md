# Smart Lab Simulator - Phase 2 (40%)

    pip install -r requirements.txt
    python app.py                 # http://127.0.0.1:5000
    pytest                        # 22 tests
    python race_demo.py           # the double-booking bug, then the fix
    python agent.py --server http://127.0.0.1:5000 --lab "Lab 1"     # run on every lab PC (key: lab123)
    gcc c/fork_demo.c -o fork_demo && ./fork_demo                    # real fork/exec/wait/pipe (Linux/WSL)

For other PCs to reach the server:  set HOST=0.0.0.0  (and LAB_KEY=your-secret) before `python app.py`.

    agent.py (each PC) --heartbeat--> app.py --> taskmgr.heartbeat --> computers + metrics tables
    browser --> app.py --> syscalls.invoke --> real OS --> syscall_log table
    booking.book --> mutex (OS) + transaction (DBMS) --> bookings --> trigger --> audit_log

The dashboard's **SQLite DBMS** panel exposes the database objects, schema columns,
row counts, and a maximum 25-row read-only preview. It does not accept arbitrary
SQL; changes continue through the validated application APIs.

See TEAM_PLAN.md for who owns what and the viva questions.

Opening the dashboard or calling `/api/computers` also reports the server's own
laptop automatically, so running only `python app.py` marks this PC available.
Previously registered PCs remain in SQLite and continue to appear; a PC that
has not sent a heartbeat for more than 20 seconds is shown as `OFFLINE` rather
than being falsely marked available.
