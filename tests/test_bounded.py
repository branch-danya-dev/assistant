import os
import subprocess
import sys
import threading
import time
from unittest.mock import patch

from support import REPO, RuntimeCase
from test_m1_create import CreateProvider

from personal_agent.bounded import run_worker
from personal_agent.config import AgentError
from personal_agent.identity import Identity
from personal_agent.journal import Journal
from personal_agent.orchestrator import Agent
from personal_agent.storage import Store


class BoundedTests(RuntimeCase):
    def test_hung_worker_has_real_deadline_and_is_reaped(self):
        popen = subprocess.Popen
        children = []

        def sleeping_child(command, **kwargs):
            child = popen([sys.executable, "-c", "import time; time.sleep(30)"], **kwargs)
            children.append(child)
            return child

        start = time.monotonic()
        with patch("personal_agent.bounded.subprocess.Popen", side_effect=sleeping_child):
            with self.assertRaisesRegex(AgentError, "operation_timeout_exhausted"):
                run_worker(self.paths, {"kind": "snapshot", "project": "alpha", "files": []}, timeout=0.3)
        self.assertLess(time.monotonic() - start, 2.5)
        self.assertIsNotNone(children[0].poll())

    def test_stop_during_dispatched_create_terminates_worker_and_never_replays(self):
        Identity(self.paths).initialize()
        self.paths.project_workspace("alpha").mkdir()
        task = self.journal.create("Synthetic", "alpha", {"files": [], "create_files": ["new.txt"],
                                                         "memory_classes": ["public", "internal"]})
        agent = Agent(self.store, CreateProvider())
        waiting = agent.run(task)
        action = waiting["actions"][0]
        self.journal.approve(action["approval_id"], action["digest"])
        popen = subprocess.Popen
        children = []
        stop_ready = threading.Event()

        def sleeping_child(command, **kwargs):
            child = popen([sys.executable, "-c", "import time; time.sleep(30)"], **kwargs)
            children.append(child)
            stop_ready.set()
            return child

        def stop():
            if stop_ready.wait(5):
                with Store(self.paths) as store:
                    Journal(store).stop()

        controller = threading.Thread(target=stop)
        controller.start()
        real_tool = agent._tool

        def delayed_tool(*args):
            # Delay the dispatched effect worker, not the new metadata preflight.
            with patch("personal_agent.bounded.subprocess.Popen", side_effect=sleeping_child):
                return real_tool(*args)

        try:
            start = time.monotonic()
            with patch.object(agent, "_tool", side_effect=delayed_tool):
                result = agent.run(task)
            self.assertLess(time.monotonic() - start, 2.5)
            self.assertEqual(result["task"]["state"], "needs_reconciliation")
            self.assertEqual(self.journal.action(action["id"])["attempts"], 1)
            self.assertFalse((self.paths.project_workspace("alpha") / "new.txt").exists())
            self.assertIsNotNone(children[0].poll())
            self.journal.stop(False)
            with self.assertRaises(AgentError):
                agent.run(task, resume=True)
        finally:
            controller.join(6)

    def test_task_wall_budget_caps_worker_timeout(self):
        task = self.task(budget={"wall_seconds": 1})
        self.journal.start(task)
        popen = subprocess.Popen

        def sleeping_child(command, **kwargs):
            return popen([sys.executable, "-c", "import time; time.sleep(30)"], **kwargs)

        start = time.monotonic()
        with patch("personal_agent.bounded.subprocess.Popen", side_effect=sleeping_child):
            with self.assertRaisesRegex(AgentError, "operation_timeout_exhausted"):
                run_worker(self.paths, {"kind": "snapshot", "project": "alpha", "files": []},
                           timeout=5, journal=self.journal, task_id=task)
        self.assertLess(time.monotonic() - start, 2.5)

    def test_parent_crash_kills_worker_tree_before_delayed_effect(self):
        marker = self.paths.root / "marker"
        sentinel = self.paths.root / "late-effect"
        # Monkeypatch only inside this fixture process; no test-only commands in production registry.
        script = '''
import os, subprocess, sys, threading, time
from personal_agent.config import Paths
from personal_agent.bounded import run_worker
real_popen = subprocess.Popen
def delayed(command, **kwargs):
    child = real_popen([sys.executable, '-c', sys.argv[4]], **kwargs)
    def crash():
        time.sleep(0.6)
        os._exit(23)
    threading.Thread(target=crash).start()
    return child
subprocess.Popen = delayed
run_worker(Paths(sys.argv[1]), {'kind': 'snapshot', 'project': 'alpha', 'files': []})
'''
        # Use worker.main's Linux parent guard, while replacing only the trusted test work function.
        child = "\n".join(["import time", "from pathlib import Path", "import personal_agent.worker as w",
                            "def delayed(payload):", f"    Path({str(marker)!r}).write_text('ready')",
                            "    time.sleep(2)", f"    Path({str(sentinel)!r}).write_text('bad')",
                            "    return {}", "w.work = delayed", "w.main()"])
        result = subprocess.run([sys.executable, "-c", script, str(self.paths.root),
                                 str(marker), str(sentinel), child], timeout=10,
                                env={**os.environ, "PYTHONPATH": str(REPO / "src")})
        self.assertEqual(result.returncode, 23)
        self.assertTrue(marker.exists(), "Fixture must reach guarded child before crashing parent")
        time.sleep(2)
        self.assertFalse(sentinel.exists())

    def test_cancel_active_read_is_task_local_and_remains_cancelled(self):
        from personal_agent.demo import DemoProvider
        Identity(self.paths).initialize()
        base = self.paths.project_workspace("alpha")
        base.mkdir()
        (base / "note.txt").write_text("synthetic")
        task = self.task(files=["note.txt"])
        agent = Agent(self.store, DemoProvider())
        popen = subprocess.Popen
        ready = threading.Event()

        def sleeping_child(command, **kwargs):
            process = popen([sys.executable, "-c", "import time; time.sleep(30)"], **kwargs)
            ready.set()
            return process

        def cancel():
            if ready.wait(5):
                with Store(self.paths) as store:
                    Journal(store).cancel(task)

        controller = threading.Thread(target=cancel)
        controller.start()
        try:
            with patch("personal_agent.bounded.subprocess.Popen", side_effect=sleeping_child):
                result = agent.run(task)
            self.assertEqual(result["task"]["state"], "cancelled", result)
            self.assertFalse(self.journal.stopped())
            with self.assertRaises(AgentError):
                agent.run(task, resume=True)
        finally:
            controller.join(6)
