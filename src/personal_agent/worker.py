"""Private entry point for the closed registry. No model-selected code or shell commands."""
from __future__ import annotations

import ctypes
import json
import os
import signal
import sys

from .config import AgentError, Paths
from .data_policy import admit
from .storage import Store, encode


def work(payload):
    paths = Paths(payload["root"])
    if payload["kind"] == "snapshot":
        from .safe_fs import snapshot
        return {p: snapshot(paths, payload["project"], p) for p in payload["files"]}
    if payload["kind"] == "model":
        from .models import Ollama
        model = Ollama(endpoint=payload["endpoint"], timeout=payload["timeout"])
        reply = model.complete(payload["messages"], task_id=payload["task_id"])
        return {"reply": reply, "metrics": model.metrics}
    if payload["kind"] == "tool":
        from .memory import Memory
        from .tools import Registry, Resolved
        with Store(paths) as store:
            registry = Registry(paths, Memory(store))
            resolved = Resolved(**payload["resolved"])
            result = registry.execute(resolved, payload["task"], payload["scope"])
            registry.verify(resolved, result, payload["task"], payload["scope"])
            return result
    raise AgentError("unknown_worker_operation")


def main():
    try:
        payload = json.loads(sys.stdin.buffer.read(262145))
        admit(payload)
        if os.name != "nt":
            # Parent-death signal is set before any tool effect; recheck the startup race.
            libc = ctypes.CDLL(None)
            if libc.prctl(1, signal.SIGKILL, 0, 0, 0) or os.getppid() != payload["parent_pid"]:
                raise AgentError("worker_parent_gone")
        reply = {"result": work(payload)}
        admit(reply)
    except Exception as exc:
        reply = {"error": str(exc) if isinstance(exc, AgentError) else "worker_operation_failed"}
    sys.stdout.buffer.write(encode(reply).encode("utf-8"))


if __name__ == "__main__":
    main()
