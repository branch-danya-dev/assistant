import json
import os
import stat
import subprocess
from unittest.mock import patch

import test_cli
from support import RuntimeCase
from test_m1_create import CreateProvider

from personal_agent.config import AgentError
from personal_agent.identity import Identity
from personal_agent.orchestrator import Agent
from personal_agent.previews import MAX_PREVIEW_BYTES, MAX_PREVIEWS, TTL_SECONDS, Previews


class PreviewTests(RuntimeCase):
    invoke = test_cli.CliTests.invoke

    def setUp(self):
        super().setUp()
        self.cache = Previews(self.store)

    def path(self, result):
        return self.paths.root / result["private_preview_relative"]

    def test_create_private_full_document_and_expiry(self):
        document = {"content": "PRIVATE_SYNTHETIC_PREVIEW", "text": "x" * 32768}
        result = self.cache.create(document, clock=1000)
        path = self.path(result)
        self.assertEqual(json.loads(path.read_text()), document)
        self.assertTrue(result["permissions_verified"])
        self.assertEqual(result["expires_at_unix"], 1000 + TTL_SECONDS)
        if os.name != "nt":
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(path.parent.stat().st_mode), 0o700)
        self.assertEqual(self.cache.cleanup(clock=1000 + TTL_SECONDS - 1)["removed"], 0)
        cleaned = self.cache.cleanup(clock=1000 + TTL_SECONDS)
        self.assertEqual(cleaned["removed"], 1)
        self.assertFalse(cleaned["cryptographic_erasure"])
        self.assertFalse(path.exists())
        self.assertEqual(self.cache.cleanup(clock=9999)["removed"], 0)

    def test_windows_acl_is_independently_user_only_and_not_inherited(self):
        if os.name != "nt":
            self.skipTest("Windows DACL inspection")
        path = self.path(self.cache.create({"synthetic": True}))
        script = r'''
$PreviewPath = $env:PREVIEW_FIXTURE_PATH
$UserSid = [System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value
foreach ($Item in @($PreviewPath, [System.IO.Path]::GetDirectoryName($PreviewPath))) {
  $Acl = if ($Item -eq $PreviewPath) { [System.IO.File]::GetAccessControl($Item) }
         else { [System.IO.Directory]::GetAccessControl($Item) }
  $Rules = @($Acl.GetAccessRules($true, $true, [System.Security.Principal.SecurityIdentifier]))
  if (!$Acl.AreAccessRulesProtected -or $Rules.Count -ne 1 -or
      $Rules[0].IdentityReference.Value -ne $UserSid -or $Rules[0].IsInherited -or
      $Rules[0].AccessControlType -ne 'Allow' -or $Rules[0].FileSystemRights -ne 'FullControl') { exit 4 }
}
'''
        result = subprocess.run(["powershell", "-NoProfile", "-Command", script],
                                env={**os.environ, "PREVIEW_FIXTURE_PATH": str(path)},
                                capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_cleanup_leaves_unregistered_and_replaced_objects_untouched(self):
        path = self.path(self.cache.create({"synthetic": True}, clock=1000))
        foreign = path.parent / "approval-00000000-0000-0000-0000-000000000000.json"
        foreign.write_text("foreign")
        path.unlink()
        # Hardlinks always fail the regular/private ownership check even if ACLs match.
        os.link(foreign, path)
        cleaned = self.cache.cleanup(clock=1000 + TTL_SECONDS)
        self.assertEqual(cleaned["removed"], 0)
        self.assertEqual(cleaned["skipped_unsafe_or_inaccessible"], 1)
        self.assertEqual(foreign.read_text(), "foreign")
        self.assertEqual(path.read_text(), "foreign")
        legacy = self.paths.directory("cache") / "approval-legacy.json"
        legacy.write_text("unregistered legacy")
        self.cache.cleanup(clock=10000)
        self.assertTrue(legacy.exists())

    def test_cleanup_does_not_follow_symlink_or_junction_cache(self):
        outside = self.paths.root / "outside"
        outside.mkdir()
        cache = self.paths.directory("cache")
        cache.rename(cache.with_name("old-cache"))
        if os.name == "nt":
            result = subprocess.run(["cmd", "/c", "mklink", "/J", str(cache), str(outside)],
                                    capture_output=True, timeout=10)
            self.assertEqual(result.returncode, 0)
        else:
            cache.symlink_to(outside, target_is_directory=True)
        with self.assertRaises((AgentError, OSError)):
            self.cache.create({"private": "CANARY"})
        self.assertEqual(list(outside.iterdir()), [])

    def test_cache_parent_cannot_be_renamed_during_windows_write(self):
        if os.name != "nt":
            self.skipTest("Linux trusts same-owner root anchors (ADR-021)")
        cache = self.paths.directory("cache")
        original = os.write
        raced = []
        def write(fd, data):
            try:
                cache.rename(cache.with_name("relocated-cache"))
            except OSError:
                raced.append(True)
            else:
                self.fail("Pinned cache renamed")
            return original(fd, data)
        with patch("personal_agent.previews.os.write", side_effect=write):
            result = self.cache.create({"private": "fixture"})
        self.assertTrue(raced)
        self.assertTrue(self.path(result).is_file())

    def test_insecure_directory_is_rejected_before_writing(self):
        self.cache.create({"first": True})
        if os.name == "nt":
            result = subprocess.run(["icacls", str(self.cache.directory), "/grant", "*S-1-1-0:(R)"],
                                    capture_output=True, timeout=10)
            self.assertEqual(result.returncode, 0)
        else:
            self.cache.directory.chmod(0o755)
        before = list(self.cache.directory.iterdir())
        with self.assertRaises(AgentError):
            self.cache.create({"must_not_write": "private"})
        self.assertEqual(list(self.cache.directory.iterdir()), before)

    def test_write_failure_unlinks_registered_partial_and_does_not_echo_payload(self):
        with patch("personal_agent.previews.os.write", side_effect=OSError("synthetic failure")):
            with self.assertRaisesRegex(AgentError, "safe_file_access_denied"):
                self.cache.create({"content": "PRIVATE_SENTINEL"})
        self.assertEqual(list(self.cache.directory.iterdir()), [])
        self.assertEqual(self.store.connection.execute("SELECT count(*) FROM approval_previews").fetchone()[0], 0)

    def test_size_count_caps_and_automatic_expiry_cleanup(self):
        with self.assertRaisesRegex(AgentError, "preview_size_exceeded"):
            self.cache.create({"text": "x" * MAX_PREVIEW_BYTES})
        first = self.path(self.cache.create({"first": True}, clock=1000))
        second = self.cache.create({"second": True}, clock=1000 + TTL_SECONDS)
        self.assertFalse(first.exists())
        self.assertEqual(second["cleanup"]["removed"], 1)
        for i in range(MAX_PREVIEWS - 1):
            self.store.connection.execute("INSERT INTO approval_previews VALUES (?,?,?)",
                                          (f"reserved-{i}", "[]", 999999))
        with self.assertRaisesRegex(AgentError, "preview_cache_full"):
            self.cache.create({"extra": True}, clock=2000)

    def test_cli_full_content_never_in_stdout_project_isolation_and_cleanup(self):
        Identity(self.paths).initialize()
        self.paths.project_workspace("alpha").mkdir()
        task = self.journal.create("Synthetic", "alpha", {
            "files": [], "create_files": ["new.txt"], "memory_classes": ["public"]})
        waiting = Agent(self.store, CreateProvider()).run(task)
        action = waiting["actions"][0]
        self.assertNotEqual(self.invoke("approval-preview", action["approval_id"],
                                       "--project", "foreign").returncode, 0)
        shown = self.invoke("approval-preview", action["approval_id"], "--project", "alpha")
        self.assertEqual(shown.returncode, 0, shown.stderr)
        self.assertNotIn("synthetic once", shown.stdout + shown.stderr)
        path = self.path(json.loads(shown.stdout))
        self.assertEqual(json.loads(path.read_text())["request"]["arguments"]["text"], "synthetic once")
        self.store.connection.execute("UPDATE approval_previews SET expires=0")
        cleaned = self.invoke("cleanup-previews")
        self.assertEqual(json.loads(cleaned.stdout)["removed"], 1)
        self.assertFalse(path.exists())

    def test_cleanup_rejects_inventory_path_escape_and_missing_files_are_forgotten(self):
        path = self.path(self.cache.create({"fixture": True}, clock=1000))
        path.unlink()
        outside = self.paths.root / "foreign.json"
        outside.write_text("foreign")
        self.store.connection.execute("INSERT INTO approval_previews VALUES (?,?,?)",
                                      ("../../foreign.json", "[]", 0))
        cleaned = self.cache.cleanup(clock=10000)
        self.assertEqual(cleaned["skipped_unsafe_or_inaccessible"], 1)
        self.assertEqual(outside.read_text(), "foreign")
        self.assertEqual(self.store.connection.execute("SELECT count(*) FROM approval_previews").fetchone()[0], 1)
        malformed = self.path(self.cache.create({"fixture": "retained"}, clock=1000))
        self.store.connection.execute("UPDATE approval_previews SET identity='invalid' WHERE name=?",
                                      (malformed.name,))
        self.assertEqual(self.cache.cleanup(clock=10000)["skipped_unsafe_or_inaccessible"], 2)
        self.assertTrue(malformed.exists())
