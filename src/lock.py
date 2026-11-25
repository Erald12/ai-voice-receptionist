import os
import time
from contextlib import contextmanager
from pathlib import Path

LOCK_MAX_AGE = 60 * 60  # seconds; an older lock is treated as left over from a crash


class AlreadyRunning(Exception):
    pass


@contextmanager
def run_lock(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and time.time() - path.stat().st_mtime < LOCK_MAX_AGE:
        raise AlreadyRunning(f"another run holds {path.name}")
    path.write_text(str(os.getpid()), encoding="utf-8")
    try:
        yield
    finally:
        path.unlink(missing_ok=True)