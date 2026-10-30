"""Synthetic files on the actual filesystem; no privileged host configuration."""
import ctypes
import io
import os
import unittest
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import asdict
from pathlib import Path
from unittest.mock import Mock, patch

from support import RuntimeCase

from personal_agent import cli
from personal_agent.bounded import run_worker
from personal_agent.config import AgentError
from personal_agent.data_policy import file_access, validate_scope
from personal_agent.identity import Identity
from personal_agent.memory import Memory
from personal_agent.orchestrator import Agent
from personal_agent.safe_fs import check_scope_paths, observe, snapshot
from personal_agent.storage import encode
from personal_agent.tools import Registry


class FileAliasTests(RuntimeCase):
    def setUp(self):
        super().setUp()
        Identity(self.paths).initialize()
        self.base = self.paths.project_workspace("alpha")
        self.base.mkdir()
        (self.base / "note.txt").write_text("SYNTHETIC_ONLY", encoding="utf-8")
        self.registry = Registry(self.paths, Memory(self.store))

    def request(self, task, path="note.txt"):
        return {"task_id": task, "capability_id": "CAP-007", "operation": "read_text",
                "arguments": {"path": path}}

    def test_exact_duplicates_and_conflicting_private_grants_denied(self):
        for scope in (
            {"files": ["note.txt", "note.txt"]},
            {"files": [], "create_files": ["new.txt", "new.txt"]},
            {"files": ["note.txt"], "private_files": ["note.txt"]},
            {"files": ["note.txt"], "private_files": ["note.txt", "note.txt"],
             "file_classes": {"note.txt": "private"}},
            {"files": ["note.txt"], "private_files": ["note.txt"],
             "file_classes": {"note.txt": "restricted"}},
            {"files": [], "create_files": ["new.txt"], "create_bindings": {"NEW.TXT": []}},
        ):
            with self.subTest(scope=scope), self.assertRaises(AgentError):
                self.journal.create("synthetic", "alpha", scope)
        self.assertEqual(self.store.connection.execute("SELECT count(*) FROM tasks").fetchone()[0], 0)

    def test_scope_validation_is_repeated_at_result_boundary(self):
        with self.assertRaisesRegex(AgentError, "ambiguous_file_scope"):
            file_access("note.txt", {"files": ["note.txt", "note.txt"]})
        with self.assertRaisesRegex(AgentError, "file_not_in_owner_scope"):
            file_access("note.txt", {"files": []})

    def test_hardlinks_denied_at_creation_and_after_scope_resolution(self):
        task = self.task(files=["note.txt"])
        document, scope = self.journal.get(task), self.journal.scope(task)
        resolved = self.registry.resolve(self.request(task), document, scope)
        os.link(self.base / "note.txt", self.base / "other.txt")
        self.assertTrue((self.base / "note.txt").samefile(self.base / "other.txt"))
        for files in (["note.txt"], ["note.txt", "other.txt"]):
            with self.assertRaisesRegex(AgentError, "non_regular_or_linked_file_denied"):
                self.journal.create("synthetic", "alpha", {"files": files})
        with patch("personal_agent.safe_fs.os.read") as read:
            with self.assertRaisesRegex(AgentError, "non_regular_or_linked_file_denied"):
                self.registry.execute(resolved, document, scope)
            read.assert_not_called()
        with self.assertRaisesRegex(AgentError, "non_regular_or_linked_file_denied"):
            run_worker(self.paths, {"kind": "tool", "resolved": asdict(resolved),
                                   "task": document, "scope": scope})

    def test_legacy_duplicate_scope_blocks_resume_without_rebinding_or_dispatch(self):
        task = self.task(files=["note.txt"])
        self.journal.start(task)
        request = self.request(task)
        self.journal.set_plan(task, [request])
        action = self.journal.prepare(task, 0, request, "read", "workspace/alpha/note.txt")
        self.journal.dispatch(action, approval_required=False)
        self.journal.finish(action, observe(self.paths, "alpha", "note.txt"))
        self.journal.transition(task, "paused")
        alias = "NOTE.TXT" if os.name == "nt" else "note.txt"
        legacy = encode({"files": ["note.txt", alias], "memory_classes": [],
                         "file_classes": {alias: "restricted"}})
        self.store.connection.execute("UPDATE tasks SET scope=? WHERE id=?", (legacy, task))
        before = dict(self.journal.action(action))
        dispatches = [e for e in self.journal.events(task) if "dispatch" in e["payload"]]
        self.assertEqual(len(dispatches), 1)
        provider = Mock()
        agent = Agent(self.store, provider)
        with patch.object(agent, "_tool") as tool:
            result = agent.run(task, resume=True)
            tool.assert_not_called()
        provider.complete.assert_not_called()
        self.assertEqual(result["task"]["state"], "blocked")
        self.assertEqual(result["task"]["block_reason"], "ambiguous_file_scope")
        self.assertEqual(dict(self.journal.action(action)), before)
        self.assertEqual(self.store.connection.execute(
            "SELECT scope FROM tasks WHERE id=?", (task,)).fetchone()[0], legacy)
        self.assertEqual([e for e in self.journal.events(task) if "dispatch" in e["payload"]],
                         dispatches)

    def test_missing_source_remains_exact_future_grant(self):
        task = self.task(files=["later.txt"])
        scope = self.journal.scope(task)
        self.assertEqual(scope["files"], ["later.txt"])
        (self.base / "later.txt").write_text("synthetic later")
        resolved = self.registry.resolve(self.request(task, "later.txt"), self.journal.get(task), scope)
        self.assertEqual(self.registry.execute(resolved, self.journal.get(task), scope)["text"],
                         "synthetic later")

    @unittest.skipUnless(os.name == "nt", "Windows filesystem aliases")
    def test_real_windows_case_alias_rejected_at_creation_registry_and_worker(self):
        self.assertTrue((self.base / "note.txt").samefile(self.base / "NOTE.TXT"))
        task = self.task(files=["note.txt"])
        document = self.journal.get(task)
        resolved = self.registry.resolve(self.request(task), document, self.journal.scope(task))
        scopes = [
            {"files": ["note.txt", "NOTE.TXT"], "file_classes": {"NOTE.TXT": label}}
            for label in ("restricted", "private", "internal")]
        scopes += [
            {"files": ["note.txt"], "create_files": ["NOTE.TXT"]},
            {"files": [], "create_files": ["new.txt", "NEW.TXT"]},
            {"files": ["note.txt"], "private_files": ["NOTE.TXT"]},
        ]
        for scope in scopes:
            with self.subTest(scope=scope):
                with self.assertRaisesRegex(AgentError, "ambiguous_file_scope"):
                    self.journal.create("synthetic", "alpha", scope)
                with self.assertRaisesRegex(AgentError, "ambiguous_file_scope"):
                    self.registry.resolve(self.request(task), document, scope)
                with self.assertRaisesRegex(AgentError, "ambiguous_file_scope"):
                    run_worker(self.paths, {"kind": "tool", "resolved": asdict(resolved),
                                           "task": document, "scope": scope})

    @unittest.skipUnless(os.name == "nt", "Windows filesystem aliases")
    def test_cli_mixed_public_private_case_alias_is_rejected(self):
        output, error = io.StringIO(), io.StringIO()
        with redirect_stdout(output), redirect_stderr(error):
            result = cli.main(["--root", str(self.paths.root), "run", "--project", "alpha",
                               "--allow-file", "note.txt", "--allow-private-file", "NOTE.TXT",
                               "synthetic"])
        self.assertEqual(result, 2)
        self.assertIn("ambiguous_file_scope", output.getvalue() + error.getvalue())
        self.assertEqual(self.store.connection.execute("SELECT count(*) FROM tasks").fetchone()[0], 0)

    @unittest.skipUnless(os.name == "nt", "Windows filesystem aliases")
    def test_single_noncanonical_case_spelling_is_not_rebound(self):
        with self.assertRaisesRegex(AgentError, "noncanonical_file_alias"):
            self.task(files=["NOTE.TXT"])
        with patch("personal_agent.safe_fs.os.read") as read:
            with self.assertRaisesRegex(AgentError, "opened_target_changed"):
                observe(self.paths, "alpha", "NOTE.TXT")
            read.assert_not_called()
        (self.base / "nested").mkdir()
        with self.assertRaisesRegex(AgentError, "noncanonical_file_alias"):
            snapshot(self.paths, "alpha", "NESTED/new.txt")

    @unittest.skipUnless(os.name == "nt", "Windows Unicode policy")
    def test_unicode_exact_names_work_but_case_and_normalization_collisions_deny(self):
        name = "записка.txt"
        (self.base / name).write_text("synthetic unicode", encoding="utf-8")
        self.assertTrue((self.base / name).samefile(self.base / name.upper()))
        self.assertEqual(observe(self.paths, "alpha", name)["text"], "synthetic unicode")
        for pair in ([name, name.upper()], ["café.txt", "cafe\u0301.txt"],
                     ["straße.txt", "strasse.txt"], ["σ.txt", "ς.txt"]):
            for item in pair:
                (self.base / item).touch(exist_ok=True)
            with self.subTest(pair=pair), self.assertRaisesRegex(AgentError, "ambiguous_file_scope"):
                self.task(files=pair)
        # Casefold/NFC does not rename a single decomposed filename or merge grants.
        self.task(files=["cafe\u0301.txt"])

    def short_name(self, path):
        from ctypes import wintypes as w
        api = ctypes.WinDLL("kernel32", use_last_error=True).GetShortPathNameW
        api.argtypes = [w.LPCWSTR, w.LPWSTR, w.DWORD]
        api.restype = w.DWORD
        buffer = ctypes.create_unicode_buffer(32768)
        length = api(str(path), buffer, len(buffer))
        if not length or length >= len(buffer):
            self.fail("GetShortPathNameW failed for synthetic fixture")
        name = Path(buffer.value).name
        if name == path.name:
            self.skipTest("8.3 alias not generated on this filesystem; no settings changed")
        return name

    @unittest.skipUnless(os.name == "nt", "Windows 8.3 filesystem aliases")
    def test_real_short_file_alias_denied_including_legacy_resume(self):
        name = "Synthetic long filename for alias.txt"
        long = self.base / name
        long.write_text("synthetic short name")
        short = self.short_name(long)
        self.assertTrue(long.samefile(self.base / short))
        with self.assertRaisesRegex(AgentError, "noncanonical_file_alias"):
            self.task(files=[short, name])
        task = self.task(files=[name])
        legacy = {"files": [short, name], "file_classes": {name: "restricted"}}
        self.store.connection.execute("UPDATE tasks SET scope=? WHERE id=?", (encode(legacy), task))
        agent = Agent(self.store, Mock())
        with patch.object(agent, "_tool") as tool:
            result = agent.run(task)
            tool.assert_not_called()
        agent.model.complete.assert_not_called()
        self.assertEqual(result["task"]["state"], "blocked")
        self.assertEqual(result["task"]["block_reason"], "noncanonical_file_alias")
        self.assertEqual(self.journal.scope(task), legacy)
        document = self.journal.get(task)
        resolved = self.registry.resolve(self.request(task, short), document, legacy)
        with self.assertRaisesRegex(AgentError, "noncanonical_file_alias"):
            run_worker(self.paths, {"kind": "tool", "resolved": asdict(resolved),
                                   "task": document, "scope": legacy})

    @unittest.skipUnless(os.name == "nt", "Windows 8.3 filesystem aliases")
    def test_real_short_directory_alias_denied_before_create(self):
        directory = self.base / "Synthetic long directory for alias"
        directory.mkdir()
        short = self.short_name(directory)
        self.assertTrue(directory.samefile(self.base / short))
        with self.assertRaisesRegex(AgentError, "noncanonical_file_alias"):
            self.journal.create("synthetic", "alpha", {"files": [],
                                "create_files": [short + "/new.txt"]})
        self.assertFalse((directory / "new.txt").exists())

    @unittest.skipUnless(os.name == "nt", "Windows directory query")
    def test_unknown_and_case_sensitive_directory_flags_fail_closed(self):
        # Real ordinary-directory query is exercised by every Windows file test.
        # These are fault-injection checks, NOT evidence of a real CS directory.
        def query(flags, success=True):
            def call(handle, kind, pointer, size):
                self.assertEqual(kind, 23)
                ctypes.cast(pointer, ctypes.POINTER(ctypes.c_ulong))[0] = flags
                return success
            return Mock(side_effect=call)
        from personal_agent.safe_fs import _win_directory_policy
        with (self.base / "note.txt").open("rb") as fixture:
            for flags, success, code in ((1, True, "case_sensitive_directory_denied"),
                                         (0, False, "directory_case_policy_unavailable")):
                with patch("ctypes.WinDLL") as dll:
                    dll.return_value.GetFileInformationByHandleEx = query(flags, success)
                    with self.assertRaisesRegex(AgentError, code):
                        _win_directory_policy(fixture.fileno())

    @unittest.skipIf(os.name == "nt", "Linux exact-name compatibility, not Windows evidence")
    def test_linux_distinct_case_and_unicode_names_keep_exact_labels(self):
        (self.base / "NOTE.TXT").write_text("synthetic restricted")
        self.assertFalse((self.base / "note.txt").samefile(self.base / "NOTE.TXT"))
        scope = {"files": ["note.txt", "NOTE.TXT"], "file_classes": {"NOTE.TXT": "restricted"}}
        task = self.journal.create("synthetic", "alpha", scope)
        file_access("note.txt", scope)
        with self.assertRaisesRegex(AgentError, "file_sensitivity_denied"):
            file_access("NOTE.TXT", scope)
        for name in ("café.txt", "cafe\u0301.txt"):
            (self.base / name).write_text("synthetic exact")
        validate_scope({"files": ["café.txt", "cafe\u0301.txt"]})
        check_scope_paths(self.paths, "alpha", self.journal.scope(task))
