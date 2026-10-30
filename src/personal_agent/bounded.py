"""Short-lived processes, not abandoned Python threads, enforce operation deadlines."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

from .config import AgentError, Paths
from .data_policy import admit
from .storage import encode

MAX_WORKER_BYTES = 262144


def worker_environment():
    # No PATH, proxy, credentials, owner PYTHON* or user environment inheritance.
    # The executable is absolute; Windows needs SystemRoot for system DLLs.
    env = {k: v for k, v in os.environ.items() if k.upper() in {"SYSTEMROOT", "WINDIR"}}
    env.update(PYTHONPATH=str(Path(__file__).resolve().parents[1]), PYTHONUTF8="1",
               PYTHONNOUSERSITE="1", PYTHONDONTWRITEBYTECODE="1")
    return env


def _windows_job(process):
    """Assign the suspended child before any Python runs; close kills it on parent exit."""
    import ctypes
    from ctypes import wintypes as w

    class Basic(ctypes.Structure):
        _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64),
                    ("PerJobUserTimeLimit", ctypes.c_int64), ("LimitFlags", w.DWORD),
                    ("MinimumWorkingSetSize", ctypes.c_size_t),
                    ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", w.DWORD),
                    ("Affinity", ctypes.c_size_t), ("PriorityClass", w.DWORD),
                    ("SchedulingClass", w.DWORD)]

    class Extended(ctypes.Structure):
        _fields_ = [("BasicLimitInformation", Basic), ("IoInfo", ctypes.c_uint64 * 6),
                    ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                    ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]

    api = ctypes.WinDLL("kernel32", use_last_error=True)
    api.CreateJobObjectW.argtypes = [ctypes.c_void_p, w.LPCWSTR]
    api.CreateJobObjectW.restype = w.HANDLE
    api.SetInformationJobObject.argtypes = [w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD]
    api.AssignProcessToJobObject.argtypes = [w.HANDLE, w.HANDLE]
    api.CloseHandle.argtypes = [w.HANDLE]
    job = api.CreateJobObjectW(None, None)
    limits = Extended()
    limits.BasicLimitInformation.LimitFlags = 0x2000 | 0x8  # kill-on-close, bounded process tree
    # Windows venv python.exe is a redirector which starts the actual interpreter.
    limits.BasicLimitInformation.ActiveProcessLimit = 2
    if (not job or not api.SetInformationJobObject(job, 9, ctypes.byref(limits), ctypes.sizeof(limits))
            or not api.AssignProcessToJobObject(job, int(process._handle))):
        if job:
            api.CloseHandle(job)
        raise AgentError("worker_lifetime_guard_failed")
    resume = ctypes.WinDLL("ntdll").NtResumeProcess
    resume.argtypes = [w.HANDLE]
    resume.restype = w.LONG
    if resume(int(process._handle)) < 0:
        api.CloseHandle(job)
        raise AgentError("worker_lifetime_guard_failed")
    return lambda: api.CloseHandle(job)


def run_worker(paths: Paths, payload: dict, *, timeout: float = 5, journal=None,
               task_id: str | None = None) -> dict:
    if task_id is not None:
        deadline = journal.get(task_id)["budget"]["deadline"]
        remaining = (datetime.fromisoformat(deadline.replace("Z", "+00:00"))
                     - datetime.now(timezone.utc)).total_seconds()
        timeout = min(timeout, remaining)
    if timeout <= 0:
        raise AgentError("wall_budget_exhausted")
    end = time.monotonic() + timeout
    payload = {**payload, "root": str(paths.root), "parent_pid": os.getpid()}
    admit(payload)
    encoded = encode(payload).encode("utf-8")
    if len(encoded) > MAX_WORKER_BYTES:
        raise AgentError("worker_input_budget_exhausted")
    # These temporary files are private runtime IPC, never artifacts or Git content.
    with tempfile.TemporaryFile(dir=paths.directory("cache")) as source, \
            tempfile.TemporaryFile(dir=paths.directory("cache")) as output:
        source.write(encoded)
        source.seek(0)
        env = worker_environment()
        flags = (0x4 | 0x08000000) if os.name == "nt" else 0  # suspended, no window
        process = subprocess.Popen([sys.executable, "-m", "personal_agent.worker"],
                                   stdin=source, stdout=output, stderr=subprocess.DEVNULL,
                                   env=env, creationflags=flags)
        def close_guard():
            pass
        try:
            if os.name == "nt":
                close_guard = _windows_job(process)
            while process.poll() is None:
                if journal is not None:
                    if journal.stopped():
                        raise AgentError("emergency_stop_active")
                    if task_id and journal.cancel_requested(task_id):
                        raise AgentError("task_cancel_requested")
                    if task_id and journal.get(task_id)["state"] != "running":
                        raise AgentError("task_not_running")
                if time.monotonic() >= end:
                    raise AgentError("operation_timeout_exhausted")
                time.sleep(min(0.025, max(0, end - time.monotonic())))
            if journal is not None and journal.stopped():
                raise AgentError("emergency_stop_active")
            if task_id and journal.cancel_requested(task_id):
                raise AgentError("task_cancel_requested")
            if time.monotonic() >= end:
                raise AgentError("operation_timeout_exhausted")
            if process.returncode != 0:
                raise AgentError("worker_interrupted")
            output.seek(0)
            raw = output.read(MAX_WORKER_BYTES + 1)
            if len(raw) > MAX_WORKER_BYTES:
                raise AgentError("worker_output_budget_exhausted")
            reply = json.loads(raw)
            admit(reply)
            if "error" in reply:
                raise AgentError(reply["error"])
            return reply["result"]
        except (ValueError, KeyError):
            raise AgentError("invalid_worker_response") from None
        finally:
            try:
                if process.poll() is None:
                    process.kill()
                    try:
                        process.wait(timeout=1)
                    except subprocess.TimeoutExpired:
                        # Kernel I/O may be uninterruptible; no success/replay claim is possible.
                        if journal is not None:
                            journal.stop()
                        raise AgentError("worker_termination_unconfirmed") from None
            finally:
                close_guard()
