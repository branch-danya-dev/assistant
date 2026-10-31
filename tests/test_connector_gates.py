import json
from pathlib import Path

from support import RuntimeCase

from personal_agent.config import AgentError, specification, validate
from personal_agent.data_policy import external_source
from personal_agent.memory import Memory
from personal_agent.tools import Registry


class ConnectorGateTests(RuntimeCase):
    def test_every_planned_class_has_complete_disabled_contract_and_adversarial_fixtures(self):
        contract = specification("connector-gates.json")
        validate("connector-gates", contract)
        fixtures = json.loads((Path(__file__).parent / "fixtures/connector-gates.json").read_text())
        task = self.task()
        registry = Registry(self.paths, Memory(self.store))
        for gate in contract["gates"]:
            self.assertEqual(set(gate["required_checks"]), {f["id"] for f in fixtures["fixtures"]})
            self.assertIsNone(gate["actual_adapter_evidence"])
            self.assertFalse(gate["enabled"])
            for fixture in fixtures["fixtures"]:
                with self.subTest(connector=gate["connector"], fixture=fixture["id"]):
                    with self.assertRaisesRegex(AgentError, fixture["expected"]):
                        external_source(gate["connector"], fixture)
            with self.assertRaisesRegex(AgentError, "unregistered_operation"):
                registry.resolve({"task_id": task, "capability_id": "CAP-007",
                    "operation": gate["connector"] + "_send", "arguments": {}},
                    self.journal.get(task), self.journal.scope(task))
        with self.assertRaisesRegex(AgentError, "external_source_not_enabled"):
            external_source("unknown_connector", {"approved": True})

    def test_contract_rejects_enablement_missing_checks_or_fake_real_evidence(self):
        for field, value in (("enabled", True), ("required_checks", ["source_classification"]),
                             ("actual_adapter_evidence", "synthetic-is-not-real")):
            contract = specification("connector-gates.json")
            contract["gates"][0][field] = value
            with self.assertRaises(AgentError):
                validate("connector-gates", contract)
