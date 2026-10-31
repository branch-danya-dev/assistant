"""Synthetic owner-attestation/inventory/legacy tests; no credentials or user DBs."""
import base64
import io
import json
import sqlite3
from contextlib import closing, redirect_stderr, redirect_stdout
from unittest.mock import Mock, patch

from support import RuntimeCase
from test_data_boundary import BoundaryCase

from personal_agent import cli
from personal_agent.config import AgentError, Paths
from personal_agent.identity import Identity
from personal_agent.memory import Memory
from personal_agent.orchestrator import Agent
from personal_agent.previews import Previews
from personal_agent.storage import MIGRATIONS, Store, encode, uid
from personal_agent.trust import Trust
from personal_agent.vault import CredentialUse, DisabledWindowsCredentialManager


class InventoryTests(BoundaryCase):
    def setUp(self):
        super().setUp()
        self.trust = Trust(self.store)

    def test_inventory_blocks_opaque_encoded_and_nested_sources_before_ipc_or_task_persistence(self):
        for index, value in enumerate((self.canary, base64.b64encode(self.canary.encode()).decode(),
                                      json.dumps({"nested": [self.canary]}))):
            path = f"opaque{index}.txt"
            (self.base / path).write_text(value, encoding="utf-8")
            self.trust.mark("file", "alpha", path)
            with patch("personal_agent.bounded.run_worker") as worker:
                with self.assertRaisesRegex(AgentError, "inventory_source_denied"):
                    self.task(files=[path])
                worker.assert_not_called()
        self.assertEqual(self.store.connection.execute("SELECT count(*) FROM tasks").fetchone()[0], 0)
        rows = [dict(r) for r in self.store.connection.execute("SELECT * FROM sensitive_inventory")]
        self.assert_absent(rows)

    def test_reviewed_inventory_does_not_override_scope_and_restricted_never_admits(self):
        (self.base / "x.txt").write_text(self.canary)
        identifier = self.trust.mark("file", "alpha", "x.txt", "internal")
        with self.assertRaisesRegex(AgentError, "inventory_source_denied"):
            self.task(files=["x.txt"])
        self.trust.review_mark(identifier, "restricted")
        with self.assertRaisesRegex(AgentError, "inventory_source_denied"):
            self.task(files=["x.txt"])
        self.trust.review_mark(identifier, "internal")
        task = self.task()  # Owner review is NOT a tool grant.
        result = Agent(self.store, self.reader()).run(task)
        self.assertEqual(result["task"]["state"], "blocked")
        allowed = self.task(files=["x.txt"])
        self.assertEqual(Agent(self.store, self.reader()).run(allowed)["task"]["state"], "completed")

    def test_late_mark_blocks_resume_and_saved_evidence_before_model_or_tool(self):
        (self.base / "x.txt").write_text(self.canary)
        task = self.task(files=["x.txt"])
        agent = Agent(self.store, self.reader())
        original = agent._final_messages
        agent._final_messages = lambda *args: (_ for _ in ()).throw(AgentError("context_budget_exhausted"))
        self.assertEqual(agent.run(task)["task"]["state"], "paused")
        before = self.journal.action(task + ":0")
        self.trust.mark("file", "alpha", "x.txt")
        agent._final_messages = original
        agent.model = Mock()
        with patch.object(agent, "_tool") as worker:
            result = agent.run(task, resume=True)
            worker.assert_not_called()
        agent.model.complete.assert_not_called()
        self.assertEqual(result["task"]["block_reason"], "inventory_source_denied")
        self.assertEqual(self.journal.action(task + ":0"), before)
        self.assert_absent(result)

    def test_memory_mark_and_changed_provenance_are_denied(self):
        memory = Memory(self.store)
        identifier = memory.remember("alpha", "needle " + self.canary, "fixture://owner", sensitivity="internal")
        self.trust.mark("memory", "alpha", identifier)
        self.assertEqual(memory.search("needle", project_id="alpha"), [])
        self.assertEqual(memory.search("", project_id="alpha"), [])
        self.assertEqual(memory.search("needle", project_id="beta"), [])
        clean = memory.remember("beta", "needle", "fixture://owner", sensitivity="internal")
        row = json.loads(self.store.connection.execute("SELECT document FROM memory WHERE id=?", (clean,)).fetchone()[0])
        row["source_refs"] = [self.canary]
        self.store.connection.execute("UPDATE memory SET document=? WHERE id=?", (encode(row), clean))
        self.assertEqual(memory.search("needle", project_id="beta"), [])

    def test_inventory_checked_before_memory_persistence_and_restricted_is_metadata_only(self):
        memory = Memory(self.store)
        with self.assertRaisesRegex(AgentError, "memory_sensitivity_denied"):
            memory.remember("alpha", self.canary, "fixture://owner", sensitivity="restricted")
        record = {"id": "known-id", "project_id": "alpha", "sensitivity": "internal"}
        self.trust.mark("memory", "alpha", record["id"])
        from personal_agent.storage import now
        record.update(statement=self.canary, kind="fact", source_refs=["fixture://owner"],
                      recorded_at=now(), supersedes=[], evidence_status="reported", retention_class="durable")
        with self.assertRaisesRegex(AgentError, "inventory_source_denied"):
            memory.add(record)
        self.assertEqual(self.store.connection.execute("SELECT count(*) FROM memory").fetchone()[0], 0)

    def test_private_sink_grants_and_unknown_sink_fail_closed(self):
        (self.base / "x.txt").write_text(self.canary)
        with self.assertRaisesRegex(AgentError, "private_sink_denied"):
            self.journal.create(self.canary, "alpha", {"files": [], "memory_classes": ["private"],
                                                      "local_sinks": ["worker", "ollama"]})
        for missing in ("worker", "ollama"):
            task = self.journal.create("synthetic", "alpha", {
                "files": ["x.txt"], "file_classes": {"x.txt": "private"}, "private_files": ["x.txt"],
                "memory_classes": [], "local_sinks": [s for s in ("worker", "journal", "ollama") if s != missing]})
            result = Agent(self.store, self.reader()).run(task)
            self.assertEqual(result["task"]["state"], "blocked")
            self.assert_absent(result)
            with self.assertRaisesRegex(AgentError, "private_sink_denied"):
                self.trust.require_task(task, sink="preview")
        task = self.task()
        with self.assertRaisesRegex(AgentError, "unclassified_sink_denied"):
            self.trust.require_task(task, sink="cloud")

    def test_inventory_expiry_and_admission_expiry_fail_closed(self):
        mark = self.trust.mark("file", "alpha", "x.txt", "internal")
        self.trust.review_mark(mark, "internal")
        self.store.connection.execute("UPDATE sensitive_inventory SET expires_at='2000-01-01T00:00:00Z'")
        with self.assertRaisesRegex(AgentError, "inventory_source_denied"):
            self.task(files=["x.txt"])
        task = self.task()
        self.store.connection.execute("UPDATE data_admissions SET expires_at='2000-01-01T00:00:00Z' WHERE kind='task'")
        provider = Mock()
        self.assertEqual(Agent(self.store, provider).run(task)["task"]["block_reason"], "source_review_required")
        provider.complete.assert_not_called()

    def test_unreviewed_legacy_resume_and_id_review_preserve_rights(self):
        (self.base / "x.txt").write_text("reviewed synthetic")
        task = self.task(files=["x.txt"])
        self.store.connection.execute("DELETE FROM data_admissions WHERE kind='task'")
        before = self.journal.scope(task)
        provider = Mock()
        result = Agent(self.store, provider).run(task)
        self.assertEqual(result["task"]["block_reason"], "source_review_required")
        provider.complete.assert_not_called()
        meta = self.trust.review_metadata("task", task, "alpha")
        with self.assertRaisesRegex(AgentError, "review_digest_or_label_mismatch"):
            self.trust.review("task", task, "alpha", "0" * 64, "internal")
        self.trust.review("task", task, "alpha", meta["digest"], "internal")
        self.assertEqual(self.journal.scope(task), before)
        self.assertEqual(Agent(self.store, self.reader()).run(task, resume=True)["task"]["state"], "completed")

    def test_review_cannot_supply_missing_legacy_labels(self):
        task = self.task(files=["x.txt"])
        scope = self.journal.scope(task)
        del scope["file_classes"]
        self.store.connection.execute("UPDATE tasks SET scope=? WHERE id=?", (encode(scope), task))
        self.store.connection.execute("DELETE FROM data_admissions WHERE kind='task'")
        meta = self.trust.review_metadata("task", task, "alpha")
        self.trust.review("task", task, "alpha", meta["digest"], "internal")
        result = Agent(self.store, Mock()).run(task)
        self.assertEqual(result["task"]["block_reason"], "file_sensitivity_denied")
        self.assertEqual(self.journal.scope(task), scope)

    def test_audit_and_cli_are_payload_free_including_private_intent_and_preview(self):
        task = self.journal.create(self.canary, "alpha", {"files": [], "memory_classes": ["private"]})
        identifier = Memory(self.store).remember("alpha", self.canary, "fixture://owner")
        preview = Previews(self.store).create({"synthetic": self.canary})
        before = self.store.connection.total_changes
        audit = self.trust.audit("alpha")
        self.assert_absent(audit)
        self.assertEqual(before, self.store.connection.total_changes)
        self.assertIn(identifier, encode(audit))
        preview_id = preview["private_preview_relative"].split("/")[-1]
        self.assertNotIn(preview_id, encode(audit))
        self.assertIn(preview_id, encode(self.trust.audit("legacy-previews")))
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            cli.main(["--root", str(self.paths.root), "show", task])
            cli.main(["--root", str(self.paths.root), "data-audit", "--project", "alpha"])
        self.assert_absent([out.getvalue(), err.getvalue()])

    def test_legacy_persona_requires_explicit_review(self):
        self.store.connection.execute("DELETE FROM data_admissions WHERE kind='persona'")
        with self.assertRaisesRegex(AgentError, "source_review_required"):
            Identity(self.paths).current()
        meta = self.trust.review_metadata("persona", "1", "identity")
        self.trust.review("persona", "1", "identity", meta["digest"], "internal")
        self.assertEqual(Identity(self.paths).current()["version"], 1)
        self.trust.mark("persona", "identity", "1")
        with self.assertRaisesRegex(AgentError, "inventory_source_denied"):
            Identity(self.paths).current()

    def test_disabled_vault_never_imports_or_calls_windows_credentials(self):
        vault = DisabledWindowsCredentialManager()
        self.assertFalse(vault.enabled)
        request = CredentialUse("synthetic-id", "telegram", "alpha", "synthetic-origin", "send")
        with patch("ctypes.WinDLL", create=True) as windows:
            with self.assertRaisesRegex(AgentError, "vault_adapter_disabled"):
                vault.use(request)
            windows.assert_not_called()
        self.assertFalse(any(hasattr(vault, name) for name in ("get", "list", "put", "import_credentials")))

    def test_owner_review_of_verified_create_never_repeats_effect_or_approval(self):
        from test_m1_create import CreateProvider
        task = self.journal.create("synthetic", "alpha", {"files": [], "memory_classes": [],
                                                          "create_files": ["new.txt"]})
        agent = Agent(self.store, CreateProvider())
        action = agent.run(task)["actions"][0]
        self.journal.approve(action["approval_id"], action["digest"])
        with patch.object(agent, "_final_messages", side_effect=AgentError("context_budget_exhausted")):
            self.assertEqual(agent.run(task)["task"]["state"], "paused")
        saved = self.journal.action(action["id"])
        approval = self.journal.approval(action["approval_id"])
        self.store.connection.execute("DELETE FROM data_admissions WHERE object_id=?", (task,))
        self.assertEqual(agent.run(task, resume=True)["task"]["block_reason"], "source_review_required")
        meta = self.trust.review_metadata("task", task, "alpha")
        self.trust.review("task", task, "alpha", meta["digest"], "internal")
        with patch.object(agent, "_tool") as worker:
            self.assertEqual(agent.run(task, resume=True)["task"]["state"], "completed")
            worker.assert_not_called()
        self.assertEqual(self.journal.action(action["id"]), saved)
        self.assertEqual(self.journal.approval(action["approval_id"]), approval)
        self.assertEqual(saved["attempts"], 1)

    def test_inventory_blocks_approved_create_before_consumption_and_preview(self):
        from test_m1_create import CreateProvider
        task = self.journal.create("synthetic", "alpha", {"files": [], "memory_classes": [],
                                                          "create_files": ["new.txt"]})
        agent = Agent(self.store, CreateProvider())
        action = agent.run(task)["actions"][0]
        self.journal.approve(action["approval_id"], action["digest"])
        approval = self.journal.approval(action["approval_id"])
        self.trust.mark("file", "alpha", "new.txt")
        with self.assertRaisesRegex(AgentError, "inventory_source_denied"):
            Previews(self.store).create({"approval": approval,
                "request": json.loads(self.journal.action(action["id"])["request"])})
        result = agent.run(task)
        self.assertEqual(result["task"]["block_reason"], "inventory_source_denied")
        self.assertEqual(self.journal.approval(action["approval_id"]), approval)
        self.assertEqual(self.journal.action(action["id"])["attempts"], 0)
        self.assertFalse((self.base / "new.txt").exists())

    def test_reindex_does_not_copy_unreviewed_or_inventory_marked_source(self):
        memory = Memory(self.store)
        identifier = memory.remember("alpha", self.canary, "fixture://owner", sensitivity="internal")
        self.trust.mark("memory", "alpha", identifier)
        memory.rebuild_index()
        self.assertEqual(self.store.connection.execute("SELECT count(*) FROM memory_fts").fetchone()[0], 0)
        self.assertEqual(self.store.connection.execute("SELECT count(*) FROM memory").fetchone()[0], 1)

    def test_unknown_sources_and_noncanonical_inventory_names_fail_closed(self):
        with self.assertRaisesRegex(AgentError, "unclassified_source_denied"):
            self.trust.guard("unknown-source", "alpha", "x")
        with self.assertRaisesRegex(AgentError, "invalid_inventory_metadata"):
            self.trust.mark("file", "alpha", "folder\\x.txt")

    def test_inventory_denial_key_is_portable_across_platform_case_unicode_policies(self):
        self.trust.mark("file", "alpha", "Caf\u00e9.txt")
        # Same conservative metadata denial on either OS, never a rewritten file grant.
        for spelling in ("Caf\u00e9.txt", "caf\u00e9.txt", "CAFE\u0301.TXT"):
            with self.assertRaisesRegex(AgentError, "inventory_source_denied"):
                self.trust.guard("file", "alpha", spelling)
        with self.assertRaises(sqlite3.IntegrityError):
            self.trust.mark("file", "alpha", "cafe\u0301.txt", "internal")


class MigrationTests(RuntimeCase):
    def legacy(self, version):
        paths = Paths(self.paths.root.parent / f"legacy-{version}-{uid()}")
        paths.bootstrap()
        connection = sqlite3.connect(paths.file("db", "agent.sqlite3"))
        connection.executescript("\n".join(MIGRATIONS[:version]) + f"PRAGMA user_version={version};")
        connection.close()
        return paths

    def test_v1_v2_v3_upgrade_backup_restore_and_idempotence(self):
        for version in (1, 2, 3):
            paths = self.legacy(version)
            with Store(paths) as upgraded:
                self.assertEqual(upgraded.connection.execute("PRAGMA user_version").fetchone()[0], 4)
                backup = paths.under(upgraded.migration_backup)
                with closing(sqlite3.connect(backup)) as old:
                    self.assertEqual(old.execute("PRAGMA user_version").fetchone()[0], version)
                    self.assertEqual(old.execute("PRAGMA integrity_check").fetchone()[0], "ok")
                self.assertEqual(upgraded.connection.execute("SELECT count(*) FROM data_admissions").fetchone()[0], 0)
            with Store(paths) as reopened:
                self.assertIsNone(reopened.migration_backup)
            self.assertEqual(len(list(paths.directory("backups").glob("*.sqlite3"))), 1)

    def test_failed_v3_migration_rolls_back_and_preserves_backup(self):
        paths = self.legacy(3)
        with patch("personal_agent.storage.MIGRATIONS", [*MIGRATIONS[:3], MIGRATIONS[3] + " INVALID SQL;"]):
            with self.assertRaises(sqlite3.Error):
                Store(paths)
        with closing(sqlite3.connect(paths.file("db", "agent.sqlite3"))) as old:
            self.assertEqual(old.execute("PRAGMA user_version").fetchone()[0], 3)
            self.assertIsNone(old.execute("SELECT name FROM sqlite_master WHERE name='data_admissions'").fetchone())
        self.assertEqual(len(list(paths.directory("backups").glob("*.sqlite3"))), 1)

    def test_negative_and_unversioned_nonempty_schema_rejected(self):
        for version in (-1, 0):
            paths = self.legacy(1)
            with closing(sqlite3.connect(paths.file("db", "agent.sqlite3"))) as db:
                db.execute(f"PRAGMA user_version={version}")
            with self.assertRaisesRegex(AgentError, "database_version_invalid"):
                Store(paths)
