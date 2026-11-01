"""Actual directory flags, ONLY inside the disposable CI-owned NTFS VHD."""
import os
import subprocess
import unittest
from dataclasses import asdict
from pathlib import Path
from unittest.mock import Mock, patch

from support import RuntimeCase

from personal_agent.bounded import run_worker
from personal_agent.config import AgentError
from personal_agent.identity import Identity
from personal_agent.memory import Memory
from personal_agent.orchestrator import Agent
from personal_agent.safe_fs import observe, snapshot
from personal_agent.tools import Registry


@unittest.skipUnless(os.name == "nt" and os.environ.get("ASSISTANT_NTFS_VHD"),
                     "requires isolated CI NTFS VHD; host flags never changed")
class RealCaseSensitiveTests(RuntimeCase):
    def setUp(self):
        super().setUp()
        volume = Path(os.environ["ASSISTANT_NTFS_VHD"])
        if (os.environ.get("GITHUB_ACTIONS") != "true" or
                os.environ.get("RUNNER_ENVIRONMENT") != "github-hosted" or
                not self.paths.root.is_relative_to(volume) or
                (volume / "task044-isolated-volume").read_text() != "synthetic-only"):
            self.fail("Refusing directory flag mutation outside CI-owned VHD")
        Identity(self.paths).initialize()
        self.base = self.paths.project_workspace("alpha")
        self.directory = self.base / "CaseDirectory"
        self.directory.mkdir(parents=True)

    def enable_real_flag(self):
        result = subprocess.run(["fsutil", "file", "setCaseSensitiveInfo", str(self.directory),
                                 "enable"], capture_output=True, text=True, timeout=15)
        print("NTFS case-sensitive enable:", result.returncode, result.stdout.strip(), result.stderr.strip())
        if result.returncode:
            self.skipTest("real per-directory case mode unavailable; fsutil exit=" + str(result.returncode))
        query = subprocess.run(["fsutil", "file", "queryCaseSensitiveInfo", str(self.directory)],
                               capture_output=True, text=True, timeout=15, check=True)
        print("NTFS actual directory query:", query.stdout.strip())
        (self.directory / "Name.txt").write_text("synthetic private", encoding="utf-8")
        (self.directory / "name.txt").write_text("synthetic internal", encoding="utf-8")
        self.assertFalse((self.directory / "Name.txt").samefile(self.directory / "name.txt"))

    def test_actual_case_mode_denied_at_admission_read_create_worker_and_resume(self):
        task = self.task(files=["CaseDirectory/Name.txt"])
        original = self.journal.scope(task)
        document = self.journal.get(task)
        request = {"task_id": task, "capability_id": "CAP-007", "operation": "read_text",
                   "arguments": {"path": "CaseDirectory/Name.txt"}}
        registry = Registry(self.paths, Memory(self.store))
        resolved = registry.resolve(request, document, original)
        self.enable_real_flag()
        for call in (
            lambda: self.task(files=["CaseDirectory/Name.txt"]),
            lambda: observe(self.paths, "alpha", "CaseDirectory/Name.txt"),
            lambda: snapshot(self.paths, "alpha", "CaseDirectory/new.txt"),
            lambda: run_worker(self.paths, {"kind": "tool", "resolved": asdict(resolved),
                                           "task": document, "scope": original}),
        ):
            with self.assertRaisesRegex(AgentError, "case_sensitive_directory_denied"):
                call()
        provider = Mock()
        agent = Agent(self.store, provider)
        with patch.object(agent, "_tool") as worker:
            result = agent.run(task)
            worker.assert_not_called()
        provider.complete.assert_not_called()
        self.assertEqual(result["task"]["block_reason"], "case_sensitive_directory_denied")
        self.assertEqual(self.journal.scope(task), original)
        self.assertFalse((self.directory / "new.txt").exists())

    def test_actual_case_mode_after_approval_does_not_consume_or_create(self):
        task = self.journal.create("synthetic", "alpha", {
            "files": [], "create_files": ["CaseDirectory/new.txt"], "memory_classes": []})
        self.journal.start(task)
        request = {"task_id": task, "capability_id": "CAP-008", "operation": "create_text",
                   "arguments": {"path": "CaseDirectory/new.txt", "text": "synthetic"}}
        self.journal.set_plan(task, [request])
        action = self.journal.prepare(task, 0, request, "workspace_write", "workspace/alpha/CaseDirectory/new.txt")
        approval = self.journal.approval(self.journal.request_approval(action))
        self.journal.approve(approval["approval_id"], approval["arguments_digest"])
        saved_action, saved_approval = self.journal.action(action), self.journal.approval(approval["approval_id"])
        self.enable_real_flag()
        result = Agent(self.store, Mock()).run(task)
        self.assertEqual(result["task"]["block_reason"], "case_sensitive_directory_denied")
        self.assertEqual(self.journal.action(action), saved_action)
        self.assertEqual(self.journal.approval(approval["approval_id"]), saved_approval)
        self.assertFalse((self.directory / "new.txt").exists())
