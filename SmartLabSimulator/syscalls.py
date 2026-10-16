"""
syscalls.py  -  System Call Interface of the Smart Lab Simulator
================================================================

In a real OS, a user program never touches hardware directly. It asks the
kernel to do the work through a SYSTEM CALL (open, read, fork, kill ...).

This module copies that idea:

    web page / user  ->  invoke("spawn", ...)  ->  syscall table  ->  real OS call
                                                        |
                                                  trace + DB log

Every call goes through ONE function, invoke(), so we can
  1. look the call up in a table (like the kernel's syscall table),
  2. run it and catch errors (return a status code like errno),
  3. time it and write it into a trace (shown in the UI, saved in the DB).
"""

import os
import platform
import subprocess
import sys
import threading
import time
from collections import deque

import psutil

# ---------------------------------------------------------------------------
# Sandbox folder: all file system calls are limited to this folder so that
# nobody can read or delete real files on the computer through the web page.
# ---------------------------------------------------------------------------
SANDBOX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "lab_files")
os.makedirs(SANDBOX, exist_ok=True)

# ---------------------------------------------------------------------------
# Programs a student is allowed to "run" in the lab. We never run text typed
# by the user (that would be a security hole), we only run these fixed ones.
# Each program is a tiny Python snippet that really runs as a separate process.
# ---------------------------------------------------------------------------
PROGRAMS = {
    # name: python code the child process will execute
    "compiler-sim": "import time\nend=time.time()+{secs}\nwhile time.time()<end: sum(range(20000))",  # uses CPU
    "editor-sim": "import time\ntime.sleep({secs})",                                              # mostly sleeps
    "matlab-sim": "import time\nend=time.time()+{secs}\nwhile time.time()<end: [i*i for i in range(30000)]",
    "browser-sim": "import time\ntime.sleep({secs})",
}

# Table of child processes created through the spawn system call.
# pid -> subprocess.Popen object. The lock protects it because Flask can
# handle two requests at the same time (threads).
_children = {}
_children_lock = threading.Lock()

# Last 200 system calls, newest at the right end.
_trace = deque(maxlen=200)

# Optional function that is called after EVERY system call (the web app uses it
# to save the call into the database). Kept as a hook so this file does not
# need to know anything about Flask or the database.
_hook = None


def set_hook(function):
    """Register a function that receives each finished syscall record."""
    global _hook
    _hook = function


class SyscallError(Exception):
    """Raised inside a syscall when something goes wrong (like errno)."""


# ===========================================================================
# PROCESS CONTROL SYSTEM CALLS
# ===========================================================================
def sys_getpid():
    """getpid(): ask the OS for the id of the current process."""
    return {"pid": os.getpid()}


def sys_getppid():
    """getppid(): id of the parent process (who started us)."""
    return {"ppid": os.getppid()}


def sys_spawn(program, seconds=30):
    """
    spawn(): create a new process.
    On Linux this is fork() + exec(). Windows has no fork(), so Python's
    subprocess.Popen does both steps in one (CreateProcess on Windows).
    """
    if program not in PROGRAMS:
        raise SyscallError("unknown program: " + str(program))

    seconds = max(1, min(int(seconds), 600))               # keep between 1 and 600 s
    code = PROGRAMS[program].format(secs=seconds)           # put the seconds into the snippet
    child = subprocess.Popen([sys.executable, "-c", code])  # <- the real process creation

    with _children_lock:
        _children[child.pid] = child
    return {"pid": child.pid, "program": program, "ppid": os.getpid()}


def _get_child(pid):
    """Helper: only processes created by spawn() can be controlled."""
    with _children_lock:
        child = _children.get(int(pid))
    if child is None:
        raise SyscallError("pid %s was not created by this simulator" % pid)
    return child


def sys_kill(pid):
    """kill(): ask the OS to terminate a process."""
    child = _get_child(pid)
    child.terminate()
    try:
        code = child.wait(timeout=3)        # wait() so the process does not stay a zombie
    except subprocess.TimeoutExpired:
        child.kill()                         # force kill if it ignores terminate
        code = child.wait(timeout=3)
    return {"pid": int(pid), "exit_code": code}


def sys_suspend(pid):
    """kill(pid, SIGSTOP): pause a process (it stays in memory but gets no CPU)."""
    child = _get_child(pid)
    psutil.Process(child.pid).suspend()
    return {"pid": child.pid, "state": "SUSPENDED"}


def sys_resume(pid):
    """kill(pid, SIGCONT): let a paused process run again."""
    child = _get_child(pid)
    psutil.Process(child.pid).resume()
    return {"pid": child.pid, "state": "RESUMED"}


def sys_wait(pid, timeout=1):
    """wait(): check whether the child finished and collect its exit code."""
    child = _get_child(pid)
    try:
        code = child.wait(timeout=float(timeout))
        return {"pid": child.pid, "finished": True, "exit_code": code}
    except subprocess.TimeoutExpired:
        return {"pid": child.pid, "finished": False, "exit_code": None}


def sys_nice(pid, level):
    """
    nice()/setpriority(): change how important a process is to the scheduler.
    level is 'low', 'normal' or 'high'.
    """
    child = _get_child(pid)
    proc = psutil.Process(child.pid)

    if os.name == "nt":                      # Windows uses "priority classes"
        classes = {
            "low": psutil.IDLE_PRIORITY_CLASS,
            "normal": psutil.NORMAL_PRIORITY_CLASS,
            "high": psutil.ABOVE_NORMAL_PRIORITY_CLASS,
        }
        if level not in classes:
            raise SyscallError("level must be low, normal or high")
        proc.nice(classes[level])
    else:                                    # Linux/Mac use nice values: bigger = less important
        values = {"low": 15, "normal": 0, "high": -5}
        if level not in values:
            raise SyscallError("level must be low, normal or high")
        proc.nice(values[level])
    return {"pid": child.pid, "priority": level}


# ===========================================================================
# FILE MANAGEMENT SYSTEM CALLS  (all inside the sandbox folder)
# ===========================================================================
def _safe_path(name):
    """Turn a file name into a full path and make sure it stays inside SANDBOX."""
    full = os.path.abspath(os.path.join(SANDBOX, name))
    if os.path.commonpath([full, SANDBOX]) != SANDBOX:
        raise SyscallError("path escapes the sandbox")
    return full


def sys_write_file(name, text):
    """open() + write() + close(): the classic three file calls."""
    path = _safe_path(name)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC)  # open -> file descriptor (a small int)
    try:
        written = os.write(fd, text.encode())                   # write bytes using the descriptor
    finally:
        os.close(fd)                                            # always close the descriptor
    return {"file": name, "fd_used": fd, "bytes_written": written}


def sys_read_file(name):
    """open() + read() + close()."""
    path = _safe_path(name)
    fd = os.open(path, os.O_RDONLY)
    try:
        data = os.read(fd, 4096)                                # read up to 4096 bytes
    finally:
        os.close(fd)
    return {"file": name, "fd_used": fd, "content": data.decode(errors="replace")}


def sys_stat(name):
    """stat(): metadata about a file (size, last modified time)."""
    info = os.stat(_safe_path(name))
    return {"file": name, "size_bytes": info.st_size, "modified": time.ctime(info.st_mtime)}


def sys_list_dir():
    """readdir(): list the files in the sandbox folder."""
    return {"files": sorted(os.listdir(SANDBOX))}


def sys_delete_file(name):
    """unlink(): delete a file."""
    os.remove(_safe_path(name))
    return {"file": name, "deleted": True}


# ===========================================================================
# INFORMATION + COMMUNICATION SYSTEM CALLS
# ===========================================================================
def sys_uname():
    """uname(): which OS and machine are we running on."""
    return {"system": platform.system(), "release": platform.release(), "machine": platform.machine()}


def sys_sysinfo():
    """sysinfo(): CPU cores, memory and uptime."""
    mem = psutil.virtual_memory()
    return {
        "cpu_cores": psutil.cpu_count(),
        "cpu_percent": psutil.cpu_percent(interval=None),
        "ram_total_mb": mem.total // (1024 * 1024),
        "ram_used_percent": mem.percent,
        "uptime_seconds": int(time.time() - psutil.boot_time()),
    }


def sys_pipe_demo(message="hello from parent"):
    """pipe(): one-way channel. Whatever is written in one end comes out the other."""
    read_end, write_end = os.pipe()          # two file descriptors
    os.write(write_end, message.encode())    # parent writes
    os.close(write_end)                      # close the writing end so read() can finish
    received = os.read(read_end, 1024)       # reader gets the bytes
    os.close(read_end)
    return {"sent": message, "received": received.decode()}


# ===========================================================================
# THE SYSTEM CALL TABLE  (name -> (function, category))
# ===========================================================================
SYSCALL_TABLE = {
    "getpid":      (sys_getpid,      "process"),
    "getppid":     (sys_getppid,     "process"),
    "spawn":       (sys_spawn,       "process"),
    "kill":        (sys_kill,        "process"),
    "suspend":     (sys_suspend,     "process"),
    "resume":      (sys_resume,      "process"),
    "wait":        (sys_wait,        "process"),
    "nice":        (sys_nice,        "process"),
    "write_file":  (sys_write_file,  "file"),
    "read_file":   (sys_read_file,   "file"),
    "stat":        (sys_stat,        "file"),
    "list_dir":    (sys_list_dir,    "file"),
    "delete_file": (sys_delete_file, "file"),
    "uname":       (sys_uname,       "information"),
    "sysinfo":     (sys_sysinfo,     "information"),
    "pipe":        (sys_pipe_demo,   "communication"),
}


def invoke(call, args=None):
    """
    The single entry point (the "trap into the kernel").
    call = name of the system call, args = dictionary of its arguments.
    Returns a record describing what happened. Never raises.
    (args is a dictionary, not **kwargs, because a call may have an argument
    called "name", e.g. the file name in write_file.)
    """
    args = dict(args or {})
    started = time.perf_counter()
    record = {
        "syscall": call,
        "category": SYSCALL_TABLE[call][1] if call in SYSCALL_TABLE else "unknown",
        "args": args,
        "caller_pid": os.getpid(),
        "time": time.strftime("%H:%M:%S"),
    }

    try:
        if call not in SYSCALL_TABLE:
            raise SyscallError("no such system call: " + str(call))
        function = SYSCALL_TABLE[call][0]
        record["result"] = function(**args)
        record["status"] = "OK"
    except (SyscallError, OSError, psutil.Error, TypeError, ValueError) as error:
        record["result"] = {"error": str(error)}
        record["status"] = "ERROR"

    record["duration_ms"] = round((time.perf_counter() - started) * 1000, 3)
    _trace.append(record)

    if _hook is not None:
        try:
            _hook(record)
        except Exception:        # logging must never break a system call
            pass
    return record


def get_trace(limit=50):
    """Return the most recent system calls, newest first."""
    return list(_trace)[-limit:][::-1]


def child_pids():
    """PIDs of all processes created through spawn()."""
    with _children_lock:
        return list(_children.keys())


def child_exit_code(pid):
    """None while the child is still alive, otherwise its exit code."""
    with _children_lock:
        child = _children.get(int(pid))
    return None if child is None else child.poll()
