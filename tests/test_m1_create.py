import json
import os
import subprocess
import sys
from dataclasses import asdict
from unittest.mock import patch

from support import REPO, RuntimeCase

from personal_agent.bounded import run_worker
from personal_agent.config import AgentError
from personal_agent.identity import Identity
from personal_agent.orchestrator import Agent
from personal_agent.safe_fs import observe, parents, snapshot
from personal_agent.storage import Store
from personal_agent.tools import Registry


class CreateProvider:
    def complete(self, messages, *, task_id):
        context = json.loads(messages[-1]["content"])
        if context["phase"] == "plan":
            return {"steps": [{"task_id": task_id, "capability_id": "CAP-008",
                               "operation": "create_text",
                               "arguments": {"path": "new.txt", "text": "synthetic once"}}],
                    "answer": "", "evidence_refs": []}
        return {"steps": [], "answer": "Created with verified evidence.",
                "evidence_refs": [o["evidence_ref"] for o in context["untrusted_observations"]]}


class CreateTests(RuntimeCase):
    def setUp(self):
        super().setUp()
        Identity(self.paths).initialize()
        self.base = self.paths.project_workspace("alpha")
        self.base.mkdir()
        self.task_id = self.journal.create("Create synthetic output", "alpha", {
            "files": [], "create_files": ["new.txt"], "memory_classes": ["public", "internal"]})
        self.agent = Agent(self.store, CreateProvider())

    def approved(self):
        result = self.agent.run(self.task_id)
        self.assertEqual(result["task"]["state"], "waiting_approval", result)
        self.assertFalse((self.base / "new.txt").exists())
        action = result["actions"][0]
        self.journal.approve(action["approval_id"], action["digest"])
        return action["id"]

    def test_real_create_exactly_once_and_side_effect_free_verify(self):
        action_id = self.approved()
        result = self.agent.run(self.task_id)
        self.assertEqual(result["task"]["state"], "completed", result)
        self.assertEqual(self.journal.action(action_id)["attempts"], 1)
        before = (self.base / "new.txt").stat()
        self.assertEqual((self.base / "new.txt").read_text(), "synthetic once")
        task, scope = self.journal.get(self.task_id), self.journal.scope(self.task_id)
        action = self.journal.action(action_id)
        resolved = self.agent.registry.resolve(json.loads(action["request"]), task, scope)
        with patch.object(Registry, "execute", side_effect=AssertionError("verifier executed a write")):
            self.agent.registry.verify(resolved, json.loads(action["result"]), task, scope)
        after = (self.base / "new.txt").stat()
        self.assertEqual((before.st_ino, before.st_mtime_ns), (after.st_ino, after.st_mtime_ns))
        with self.assertRaises(AgentError):
            self.agent.run(self.task_id, resume=True)

    def test_existing_file_and_hardlink_never_changed(self):
        action_id = self.approved()
        victim = self.base / "original.txt"
        victim.write_text("preserve original")
        real_tool = self.agent._tool

        def link_after_dispatch(*args):
            # Reproduce a race after preflight; the worker must still refuse.
            os.link(victim, self.base / "new.txt")
            return real_tool(*args)

        with patch.object(self.agent, "_tool", side_effect=link_after_dispatch):
            result = self.agent.run(self.task_id)
        self.assertEqual(result["task"]["state"], "needs_reconciliation")
        self.assertEqual(victim.read_text(), "preserve original")
        self.assertEqual(self.journal.action(action_id)["attempts"], 1)
        with self.assertRaises(AgentError):
            observe(self.paths, "alpha", "new.txt")

    def test_preflight_hardlink_denial_preserves_unused_create_approval(self):
        action_id = self.approved()
        before = dict(self.journal.action(action_id))
        approval = dict(self.journal.approval(before["approval_id"]))
        victim = self.base / "original.txt"
        victim.write_text("preserve original")
        os.link(victim, self.base / "new.txt")
        with patch.object(self.agent, "_tool") as tool:
            result = self.agent.run(self.task_id)
            tool.assert_not_called()
        self.assertEqual(result["task"]["state"], "blocked")
        self.assertEqual(dict(self.journal.action(action_id)), before)
        self.assertEqual(dict(self.journal.approval(before["approval_id"])), approval)
        self.assertEqual(victim.read_text(), "preserve original")

    def test_parent_replaced_after_approval_is_denied(self):
        action_id = self.approved()
        old = self.base.with_name("moved-alpha")
        self.base.rename(old)
        self.base.mkdir()
        result = self.agent.run(self.task_id)
        self.assertEqual(result["task"]["state"], "needs_reconciliation")
        self.assertFalse((old / "new.txt").exists())
        self.assertFalse((self.base / "new.txt").exists())
        self.assertEqual(self.journal.action(action_id)["attempts"], 1)

    def test_traversal_ads_reserved_and_missing_parent(self):
        for target in ("../x", "a.txt:secret", "CON", "NUL.txt", "dir./x", "/x", "C:/x",
                       "\\\\server/share/x", "a/../../x", "a\\..\\x", "missing/x.txt"):
            with self.subTest(target=target), self.assertRaises(AgentError):
                self.journal.create("Synthetic", "alpha", {
                    "files": [], "create_files": [target], "memory_classes": ["public"]})

    def test_write_is_never_allowed_by_read_scope_or_model_risk_hint(self):
        task = self.journal.get(self.task_id)
        request = {"task_id": self.task_id, "capability_id": "CAP-008", "operation": "create_text",
                   "arguments": {"path": "new.txt", "text": "x"}}
        with self.assertRaises(AgentError):
            self.agent.registry.resolve(request, task, {"files": ["new.txt"]})
        with self.assertRaises(AgentError):
            self.agent.registry.resolve({**request, "approval_required": False}, task,
                                        self.journal.scope(self.task_id))

    def test_real_crash_after_create_before_ack_never_replays(self):
        action_id = self.approved()
        script = '''
import json, os, sys
from personal_agent.config import Paths
from personal_agent.storage import Store
from personal_agent.journal import Journal
from personal_agent.memory import Memory
from personal_agent.tools import Registry
with Store(Paths(sys.argv[1])) as store, store.execution_lock():
    journal = Journal(store)
    journal.start(sys.argv[2])
    action = journal.action(sys.argv[3])
    task, scope = journal.get(sys.argv[2]), journal.scope(sys.argv[2])
    registry = Registry(store.paths, Memory(store))
    resolved = registry.resolve(json.loads(action['request']), task, scope)
    journal.dispatch(action['id'], approval_required=True)
    registry.execute(resolved, task, scope)
    os._exit(17)
'''
        process = subprocess.run([sys.executable, "-c", script, str(self.paths.root),
                                  self.task_id, action_id], timeout=20,
                                 env={**os.environ, "PYTHONPATH": str(REPO / "src")})
        self.assertEqual(process.returncode, 17)
        self.assertEqual((self.base / "new.txt").read_text(), "synthetic once")
        with self.store.execution_lock():
            self.journal.recover()
        self.assertEqual(self.journal.get(self.task_id)["state"], "needs_reconciliation")
        with self.assertRaises(AgentError):
            self.agent.run(self.task_id, resume=True)
        self.assertEqual(self.journal.action(action_id)["attempts"], 1)
        self.journal.reconcile(action_id, "applied", "fixture://independently-observed", project="alpha",
            expected_digest=self.journal.trust.review_metadata("task", self.task_id, "alpha")["digest"])
        shown = self.journal.inspect(self.task_id)
        self.assertFalse(shown.get("content_withheld", False))
        self.assertEqual(shown["actions"][0]["reconciliation"]["outcome"], "applied")
        self.assertEqual(self.journal.trust.review_metadata("task", self.task_id, "alpha")["review"], "current")
        with self.assertRaises(AgentError):
            self.agent.run(self.task_id, resume=True)

    def test_windows_pins_all_ancestors_during_create(self):
        if os.name != "nt":
            self.skipTest("Windows sharing semantics")
        child = self.base / "nested"
        child.mkdir()
        with parents(self.paths, "alpha", "nested/new.txt"):
            for folder in (child, self.base, self.paths.directory("workspace")):
                with self.assertRaises(OSError):
                    folder.rename(folder.with_name(folder.name + "-swap"))

    def test_uncertain_create_not_applied_reconciliation_never_publishes_file(self):
        action_id = self.approved()
        self.journal.start(self.task_id)
        self.journal.dispatch(action_id, approval_required=True)
        # Crash point before adapter entry: consumed approval, no published bytes.
        with self.store.execution_lock():
            self.journal.recover()
        old = self.journal.action(action_id)
        self.journal.reconcile(action_id, "not_applied", "fixture://observed-absent", project="alpha",
            expected_digest=self.journal.trust.review_metadata("task", self.task_id, "alpha")["digest"])
        self.assertEqual(self.journal.inspect(self.task_id)["actions"][0]["reconciliation"]["outcome"], "not_applied")
        with self.assertRaises(AgentError):
            self.agent.run(self.task_id, resume=True)
        self.assertFalse((self.base / "new.txt").exists())
        self.assertEqual(self.journal.action(action_id)["attempts"], old["attempts"])
        self.assertEqual(self.journal.approval(old["approval_id"])["status"], "consumed")

    def test_junction_or_symlink_parent_denied(self):
        outside = self.paths.root / "outside"
        outside.mkdir()
        link = self.base / "link"
        if os.name == "nt":
            source = str(link).replace("'", "''")
            dest = str(outside).replace("'", "''")
            subprocess.run(["powershell", "-NoProfile", "-Command",
                            f"New-Item -ItemType Junction -Path '{source}' -Target '{dest}' | Out-Null"],
                           check=True, capture_output=True, timeout=20)
        else:
            link.symlink_to(outside, target_is_directory=True)
        try:
            with self.assertRaises(AgentError):
                snapshot(self.paths, "alpha", "link/new.txt")
        finally:
            link.rmdir() if os.name == "nt" else link.unlink()

    def test_worker_result_has_no_duplicate_create_dispatch(self):
        # A second execution would fail exclusive-create; production worker completes successfully.
        self.approved()
        task, scope = self.journal.get(self.task_id), self.journal.scope(self.task_id)
        request = self.journal.plan(self.task_id)[0]
        resolved = self.agent.registry.resolve(request, task, scope)
        result = run_worker(self.paths, {"kind": "tool", "resolved": asdict(resolved),
                                        "task": task, "scope": scope})
        self.assertEqual(result["bytes"], len("synthetic once"))
        with Store(self.paths) as reopened:
            self.assertEqual(reopened.connection.execute("PRAGMA integrity_check").fetchone()[0], "ok")

    def test_owner_can_review_exact_approval_in_private_artifact_without_stdout_content(self):
        import test_cli
        waiting = self.agent.run(self.task_id)
        action = waiting["actions"][0]
        result = test_cli.CliTests.invoke(self, "approval-preview", action["approval_id"],
                                         "--project", "alpha")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("synthetic once", result.stdout)
        metadata = json.loads(result.stdout)
        preview = json.loads((self.paths.root / metadata["private_preview_relative"]).read_text())
        self.assertEqual(preview["request"]["arguments"]["text"], "synthetic once")
        self.assertEqual(preview["approval"]["arguments_digest"], action["digest"])
        denied = test_cli.CliTests.invoke(self, "approval-preview", action["approval_id"],
                                         "--project", "other")
        self.assertEqual(denied.returncode, 2)

    def test_linux_kernel_denies_root_moved_out_after_open_before_publish(self):
        if os.name == "nt":
            self.skipTest("Linux Landlock publication race")
        outside = self.paths.root.parent / "outside"
        script = '''
import os, subprocess, sys
from personal_agent.config import Paths, AgentError
import personal_agent.safe_fs as fs
paths = Paths(sys.argv[1])
binding = fs.snapshot(paths, 'alpha', 'new.txt')
helper_code = "import os,sys; sys.stdin.read(1); os.rename(sys.argv[1],sys.argv[2]); print('done',flush=True)"
helper = subprocess.Popen([sys.executable, '-c', helper_code, sys.argv[2], sys.argv[3]],
                          stdin=subprocess.PIPE, stdout=subprocess.PIPE)
original = fs._publish_linux
def race(fd, parent, name):
    helper.stdin.write(b'x')
    helper.stdin.flush()
    assert helper.stdout.readline() == b'done\\n'
    original(fd, parent, name)
fs._publish_linux = race
try:
    fs.create_text(paths, 'alpha', 'new.txt', 'private synthetic text', binding)
except AgentError as error:
    assert str(error) == 'exclusive_file_publish_failed', str(error)
    sys.exit(0)
sys.exit(4)
'''
        result = subprocess.run([sys.executable, "-c", script, str(self.paths.root), str(self.base),
                                 str(outside)], capture_output=True, text=True, timeout=20,
                                env={**os.environ, "PYTHONPATH": str(REPO / "src")})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(outside.exists(), "Attack must actually move the pinned parent")
        self.assertFalse((outside / "new.txt").exists())

    def test_linux_nested_create_is_denied_before_dispatch(self):
        if os.name == "nt":
            self.skipTest("Linux flat-output restriction")
        (self.base / "nested").mkdir()
        task_id = self.journal.create("Nested synthetic", "alpha", {
            "files": [], "create_files": ["nested/file.txt"], "memory_classes": ["public"]})
        request = {"task_id": task_id, "capability_id": "CAP-008", "operation": "create_text",
                   "arguments": {"path": "nested/file.txt", "text": "data"}}
        with self.assertRaisesRegex(AgentError, "nested_create_requires_windows"):
            self.agent.registry.resolve(request, self.journal.get(task_id), self.journal.scope(task_id))
        self.assertFalse((self.base / "nested/file.txt").exists())

    def test_duplicate_create_intents_cannot_dispatch_same_effect_twice(self):
        class Duplicate(CreateProvider):
            def complete(self, messages, *, task_id):
                reply = super().complete(messages, task_id=task_id)
                if reply["steps"]:
                    reply["steps"] *= 2
                return reply
        self.agent.model = Duplicate()
        action_id = self.approved()
        result = self.agent.run(self.task_id)
        self.assertEqual(result["task"]["state"], "blocked")
        self.assertEqual(result["task"]["block_reason"], "non_idempotent_plan_replay_denied")
        self.assertEqual(result["task"]["budget"]["tool_calls"], 1)
        self.assertEqual(self.journal.action(action_id)["attempts"], 1)

    def test_windows_nested_create_is_supported_with_pinned_parents(self):
        if os.name != "nt":
            self.skipTest("Windows supports nested outputs")
        (self.base / "nested").mkdir()
        task_id = self.journal.create("Nested synthetic", "alpha", {
            "files": [], "create_files": ["nested/file.txt"], "memory_classes": ["public"]})
        task, scope = self.journal.get(task_id), self.journal.scope(task_id)
        request = {"task_id": task_id, "capability_id": "CAP-008", "operation": "create_text",
                   "arguments": {"path": "nested/file.txt", "text": "nested once"}}
        resolved = self.agent.registry.resolve(request, task, scope)
        result = run_worker(self.paths, {"kind": "tool", "resolved": asdict(resolved),
                                        "task": task, "scope": scope})
        self.assertEqual(result["bytes"], 11)
        self.assertEqual((self.base / "nested/file.txt").read_text(), "nested once")
