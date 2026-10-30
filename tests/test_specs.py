"""Contract and repository validation tests (not application runtime tests)."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "src"))

from validate_specs import check, load  # noqa: E402
from personal_agent.ports import SideEffect, ToolRequest, ToolResult  # noqa: E402


class SpecTests(unittest.TestCase):
    def test_cross_references_and_security_invariants(self):
        self.assertEqual(check(), [])

    def test_minimum_scenarios_are_defined(self):
        scenarios = load("spec/scenarios.json")["scenarios"]
        self.assertGreaterEqual(len(scenarios), 5)
        self.assertTrue(all(x["status"] == "specified" for x in scenarios))

    def test_no_capabilities_misrepresented_as_implemented(self):
        caps = load("spec/capabilities.json")["capabilities"]
        self.assertTrue(all(c["status"] == "planned" for c in caps))

    def test_provisional_decisions_are_not_owner_approved(self):
        decisions = load("spec/decisions.json")["decisions"]
        self.assertTrue(any(d["status"] == "provisional" for d in decisions))
        self.assertTrue(any(d["status"] == "accepted" for d in decisions))

    def test_accepted_storage_policy(self):
        storage = load("spec/storage-config.json")
        self.assertEqual(storage["default_root"], "G:\\Assistant")
        self.assertEqual(storage["layout"]["repository"], "repo")
        self.assertEqual(storage["layout"]["models_ollama"], "models/ollama")
        self.assertEqual(storage["ollama"]["default_model_storage"], "G:\\Assistant\\models\\ollama")
        self.assertTrue(storage["relative_path_policy"]["no_silent_fallback_to_system_disk"])

    def test_ports_are_importable(self):
        request = ToolRequest("CAP-007", "runtime-task-id", {"path": "example.txt"}, SideEffect.READ)
        result = ToolResult(True, {"name": "example"})
        self.assertEqual(request.side_effect, SideEffect.READ)
        self.assertTrue(result.success)


if __name__ == "__main__":
    unittest.main()
