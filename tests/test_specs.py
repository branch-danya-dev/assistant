"""Canonical contract and evidence validation, separate from runtime behavior tests."""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "src"))

from validate_specs import check, load  # noqa: E402

from personal_agent.ports import ToolRequest, ToolResult  # noqa: E402


class SpecTests(unittest.TestCase):
    def test_semantic_security_deadlock_without_work_dag_cycle(self):
        def mutated(path):
            value = load(path)
            if path == "spec/tasks.json":
                task = next(t for t in value["tasks"] if t["id"] == "TASK-044")
                task["depends_on"].append("TASK-026")
            return value
        with patch("validate_specs.load", side_effect=mutated):
            errors = check()
        self.assertTrue(any("acceptance dependency cycle" in e for e in errors), errors)
        self.assertFalse(any(e.startswith("task dependency cycle") for e in errors), errors)

    def test_security_gate_is_independently_startable_and_completion_is_not_a_status_shortcut(self):
        tasks = {t["id"]: t for t in load("spec/tasks.json")["tasks"]}
        self.assertEqual(set(tasks["TASK-044"]["depends_on"]), {"TASK-004", "TASK-005"})
        self.assertTrue(all(tasks[t]["status"] == "done" for t in tasks["TASK-044"]["depends_on"]))
        self.assertEqual(tasks["TASK-026"]["acceptance_depends_on"], ["TASK-044"])
        def mutated(path):
            value = load(path)
            if path == "spec/tasks.json":
                next(t for t in value["tasks"] if t["id"] == "TASK-026")["status"] = "done"
            return value
        with patch("validate_specs.load", side_effect=mutated):
            self.assertIn("TASK-026: done before acceptance gate", check())

    def test_milestone_cannot_be_completed_with_unimplemented_p0(self):
        def mutated(path):
            value = load(path)
            if path == "spec/milestones.json":
                next(m for m in value["milestones"] if m["id"] == "M1")["status"] = "completed"
            return value
        with patch("validate_specs.load", side_effect=mutated):
            errors = check()
        self.assertIn("M1: completed with open P0 REQ-017", errors)
        self.assertIn("M1: completed with open P0 REQ-019", errors)

    def test_machine_readable_contracts_and_full_requirement_coverage(self):
        self.assertEqual(check(), [])
        requirements = load("spec/requirements.json")["requirements"]
        covered = {ref for task in load("spec/tasks.json")["tasks"] for ref in task["requirement_ids"]}
        self.assertTrue(all(r["id"] in covered for r in requirements if r["status"] != "deprecated"))

    def test_selected_model_not_compared(self):
        selected = load("spec/model-config.json")
        self.assertEqual(selected["primary_local"]["model"], "qwen3.5:9b")
        self.assertEqual(selected["selection_policy"]["comparative_model_benchmarks"], "not_required")

    def test_windows_single_root(self):
        storage = load("spec/storage-config.json")
        self.assertEqual(storage["default_root"], "G:" + chr(92) + "Assistant")
        self.assertEqual(storage["layout"]["models_ollama"], "models/ollama")
        self.assertTrue(storage["path_resolution"]["migration_change_only_app_root"])

    def test_model_intent_cannot_spoof_effects(self):
        schema = load("spec/schemas/tool-invocation.schema.json")
        invocation = load("spec/examples/tool-invocation.json")
        self.assertTrue(Draft202012Validator(schema).is_valid(invocation))
        self.assertFalse(Draft202012Validator(schema).is_valid({**invocation, "side_effect": "read"}))
        self.assertFalse(Draft202012Validator(schema).is_valid({**invocation, "approval_required": False}))

    def test_github_write_requires_approval(self):
        caps = {c["id"]: c for c in load("spec/capabilities.json")["capabilities"]}
        self.assertEqual(caps["CAP-022"]["side_effect"], "read")
        self.assertEqual(caps["CAP-028"]["policy"], "approval")

    def test_verified_scenarios_require_actual_evidence(self):
        scenarios = load("spec/scenarios.json")["scenarios"]
        self.assertGreaterEqual(len(scenarios), 11)
        self.assertTrue(all(x["status"] in ("specified", "verified") for x in scenarios))
        for scenario in scenarios:
            if scenario["status"] == "verified":
                self.assertTrue(scenario["evidence"])
                for path in scenario["evidence"]:
                    self.assertTrue((ROOT / path).is_file())

    def test_stub_ports_import(self):
        req = ToolRequest("CAP-022", "read_repo", "task-001", {"repo": "example/repo"})
        res = ToolResult(True, {"entries": []})
        self.assertEqual(req.operation, "read_repo")
        self.assertTrue(res.success)


if __name__ == "__main__":
    unittest.main()
