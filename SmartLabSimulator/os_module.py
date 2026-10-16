"""Kept for compatibility. The real work now lives in task_manager.py."""
import task_manager


def get_processes(limit=20):
    return task_manager.system_processes(limit=limit, sort_by="cpu")
