from __future__ import annotations

import datetime as dt
import itertools
import threading


_lock = threading.Lock()
_counter = itertools.count(1)


def now_text() -> str:
    return dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def new_id(prefix: str) -> str:
    stamp = dt.datetime.now().strftime("%Y%m%d%H%M%S")
    with _lock:
        seq = next(_counter)
    return f"{prefix}{stamp}{seq:04d}"


def task_no() -> str:
    stamp = dt.datetime.now().strftime("%Y%m%d")
    with _lock:
        seq = next(_counter)
    return f"TASK-{stamp}-{seq:04d}"

