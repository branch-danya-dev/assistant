import json
import os
import subprocess
import sys

from support import REPO, RuntimeCase


class CliTests(RuntimeCase):
    def invoke(self, *arguments):
        return subprocess.run([sys.executable, "-m", "personal_agent", "--root", str(self.paths.root),
                               *arguments], env={**os.environ, "PYTHONPATH": str(REPO / "src")},
                              capture_output=True, text=True, encoding="utf-8", timeout=20, check=False)

    def test_demo_task_inspection_and_stop_across_processes(self):
        result = self.invoke("demo")
        self.assertEqual(result.returncode, 0, result.stderr)
        task_id = json.loads(result.stdout)["task"]["task_id"]
        shown = self.invoke("show", task_id)
        self.assertEqual(json.loads(shown.stdout)["task"]["state"], "completed")
        self.assertEqual(self.invoke("stop").returncode, 0)
        self.assertTrue(self.journal.stopped())
        self.assertEqual(self.invoke("clear-stop").returncode, 0)
        self.assertFalse(self.journal.stopped())

    def test_owner_memory_cli_removal_and_private_scope(self):
        added = self.invoke("memory", "add", "synthetic private note", "--project", "alpha",
                            "--source", "fixture://owner")
        record_id = json.loads(added.stdout)["record_id"]
        public = self.invoke("memory", "search", "note", "--project", "alpha")
        self.assertEqual(json.loads(public.stdout)["records"], [])
        private = self.invoke("memory", "search", "note", "--project", "alpha", "--include-private")
        self.assertEqual(len(json.loads(private.stdout)["records"]), 1)
        removed = self.invoke("memory", "remove", record_id, "--project", "alpha")
        self.assertTrue(json.loads(removed.stdout)["removed_from_retrieval"])
        self.assertFalse(json.loads(removed.stdout)["physical_and_backup_erasure"])

    def test_errors_do_not_echo_private_input(self):
        result = self.invoke("memory", "add", "PRIVATE_SENTINEL", "--project", "../invalid",
                             "--source", "fixture://owner")
        self.assertEqual(result.returncode, 2)
        self.assertNotIn("PRIVATE_SENTINEL", result.stderr + result.stdout)
