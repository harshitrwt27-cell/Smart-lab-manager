"""
syscalls.py - MEMBER 1 (OS: system calls + process creation)   (DB: syscall_log + view)

A user program never touches the hardware. It asks the kernel through a SYSTEM CALL.
Here every action goes through ONE function, invoke(), which
   1. looks the call up in a table      (like the kernel's syscall table)
   2. runs it and turns errors into a status
   3. saves the call in the database    (the audit trail)
"""
import json
import os
import subprocess
import sys
import threading
import time

import psutil

import db

SANDBOX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "lab_files")
os.makedirs(SANDBOX, exist_ok=True)

# Only these fixed programs can be started. We never run text typed by a user.
PROGRAMS = {
    "compiler-sim": "import time\nend=time.time()+{s}\nwhile time.time()<end: sum(range(20000))",  # burns CPU
    "editor-sim": "import time\ntime.sleep({s})",                                                 # sleeps
}
children = {}                    # pid -> Popen object of every process we created
children_lock = threading.Lock()


class SyscallError(Exception):
    pass


# ---------------- process calls ----------------
def sys_getpid():
    """getpid(): id of the running process."""
    return {"pid": os.getpid()}


def sys_spawn(program, seconds=30):
    """spawn(): create a process (fork+exec on Linux, CreateProcess on Windows)."""
    if program not in PROGRAMS:
        raise SyscallError("unknown program " + str(program))
    code = PROGRAMS[program].format(s=max(1, min(int(seconds), 600)))
    child = subprocess.Popen([sys.executable, "-c", code])     # <- the real process creation
    with children_lock:
        children[child.pid] = child
    return {"pid": child.pid, "parent": os.getpid()}


def _child(pid):
    with children_lock:
        if int(pid) not in children:
            raise SyscallError("pid %s was not created by this simulator" % pid)
        return children[int(pid)]


def sys_kill(pid):
    """kill(): terminate a process, then wait() so it does not stay a zombie."""
    child = _child(pid)
    child.terminate()
    try:
        return {"pid": child.pid, "exit_code": child.wait(timeout=3)}
    except subprocess.TimeoutExpired:
        child.kill()
        return {"pid": child.pid, "exit_code": child.wait(timeout=3)}


def sys_suspend(pid):
    """suspend(): pause a process (SIGSTOP). It stays in memory but gets no CPU."""
    psutil.Process(_child(pid).pid).suspend()
    return {"pid": int(pid), "state": "SUSPENDED"}


def sys_resume(pid):
    """resume(): continue a paused process (SIGCONT)."""
    psutil.Process(_child(pid).pid).resume()
    return {"pid": int(pid), "state": "RESUMED"}


def sys_wait(pid, timeout=1):
    """wait(): has the child finished? returns its exit code."""
    try:
        return {"pid": int(pid), "finished": True, "exit_code": _child(pid).wait(timeout=float(timeout))}
    except subprocess.TimeoutExpired:
        return {"pid": int(pid), "finished": False, "exit_code": None}


# ---------------- file calls (inside the sandbox folder only) ----------------
def _path(name):
    full = os.path.abspath(os.path.join(SANDBOX, name))
    if os.path.commonpath([full, SANDBOX]) != SANDBOX:
        raise SyscallError("path is outside the sandbox")
    return full


def sys_write_file(name, text):
    """open() + write() + close()."""
    fd = os.open(_path(name), os.O_WRONLY | os.O_CREAT | os.O_TRUNC)   # fd = small integer handle
    try:
        return {"file": name, "bytes_written": os.write(fd, text.encode())}
    finally:
        os.close(fd)


def sys_read_file(name):
    """open() + read() + close()."""
    fd = os.open(_path(name), os.O_RDONLY)
    try:
        return {"file": name, "content": os.read(fd, 4096).decode(errors="replace")}
    finally:
        os.close(fd)


# ---------------- communication ----------------
def sys_pipe(message="hello"):
    """pipe(): a one-way channel. What goes into one end comes out of the other."""
    read_end, write_end = os.pipe()
    os.write(write_end, message.encode())
    os.close(write_end)
    received = os.read(read_end, 1024).decode()
    os.close(read_end)
    return {"sent": message, "received": received}


TABLE = {"getpid": sys_getpid, "spawn": sys_spawn, "kill": sys_kill, "suspend": sys_suspend,
         "resume": sys_resume, "wait": sys_wait, "write_file": sys_write_file,
         "read_file": sys_read_file, "pipe": sys_pipe}


def invoke(call, args=None):
    """The ONE entry point. Never raises: returns {call, status, result, ms}."""
    args = dict(args or {})
    started = time.perf_counter()
    try:
        if call not in TABLE:
            raise SyscallError("no such system call: " + str(call))
        result, status = TABLE[call](**args), "OK"
    except (SyscallError, OSError, psutil.Error, TypeError, ValueError) as error:
        result, status = {"error": str(error)}, "ERROR"
    ms = round((time.perf_counter() - started) * 1000, 3)
    db.execute("INSERT INTO syscall_log(call, args, status, ms) VALUES (?, ?, ?, ?)",
               (call, json.dumps(args), status, ms))                       # save in the DBMS
    return {"call": call, "args": args, "status": status, "result": result, "ms": ms}
