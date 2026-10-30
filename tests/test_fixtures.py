"""M0 fixture rubric, not a claim that M2/M3 adapters are implemented."""
import json
import unittest
from pathlib import Path


class FixtureTests(unittest.TestCase):
    def test_synthetic_scenario_rubric_and_threat_mapping(self):
        fixture = json.loads((Path(__file__).parent / "fixtures/acceptance.json").read_text())
        self.assertTrue(fixture["synthetic_only"])
        self.assertEqual({s["id"] for s in fixture["scenarios"]},
                         {f"SCN-{n:03}" for n in range(1, 6)})
        for scenario in fixture["scenarios"]:
            for key in ("inputs", "expected", "gate", "failure"):
                self.assertTrue(scenario[key])
        self.assertEqual(len(fixture["threats"]), 9)
        for threat in fixture["threats"]:
            self.assertTrue(threat["input"])
            self.assertTrue(threat["expected"])
            self.assertRegex(threat["regression"], r"^tests/test_.*\.py::test_")
