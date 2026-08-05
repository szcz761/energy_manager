"""
Cross-platform file locking utility.

Uses fcntl on Linux/Mac and msvcrt on Windows.
Provides a context manager for exclusive file locks.
"""
from __future__ import annotations

import os
import sys

# Platform-specific locking
if sys.platform == "win32":
    import msvcrt
    
    def _lock(fp):
        msvcrt.locking(fp.fileno(), msvcrt.LK_NBLCK, 1)
    
    def _unlock(fp):
        try:
            fp.seek(0)
            msvcrt.locking(fp.fileno(), msvcrt.LK_UNLCK, 1)
        except (IOError, OSError):
            pass
else:
    import fcntl
    
    def _lock(fp):
        fcntl.flock(fp, fcntl.LOCK_EX | fcntl.LOCK_NB)
    
    def _unlock(fp):
        fcntl.flock(fp, fcntl.LOCK_UN)


class FileLock:
    """
    Non-blocking exclusive file lock.
    
    Usage:
        lock = FileLock("/path/to/.mylock")
        if not lock.acquire():
            sys.exit(0)  # Another instance running
        try:
            # do work
        finally:
            lock.release()
    """
    
    def __init__(self, path: str):
        self.path = path
        self._fp = None
    
    def acquire(self) -> bool:
        """Try to acquire lock. Returns True on success, False if already locked."""
        self._fp = open(self.path, "w")
        try:
            _lock(self._fp)
            return True
        except (IOError, OSError):
            self._fp.close()
            self._fp = None
            return False
    
    def release(self) -> None:
        """Release lock and clean up."""
        if self._fp:
            _unlock(self._fp)
            self._fp.close()
            self._fp = None
            try:
                os.unlink(self.path)
            except OSError:
                pass
    
    def __enter__(self):
        if not self.acquire():
            raise OSError("Could not acquire lock")
        return self
    
    def __exit__(self, *args):
        self.release()
