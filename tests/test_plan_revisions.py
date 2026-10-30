import copy
import json
from unittest.mock import patch

from support import RuntimeCase
from test_m1_create import CreateProvider

from personal_agent.config import AgentError
from personal_agent.identity import Identity
from personal_agent.orchestrator import Agent
from personal_agent.storage import Store


class RevisionTests(RuntimeCase):
    def setUp(self):
        super().setUp()
        Identity(self.paths).initialize()
        self.paths.project_workspace("alpha").mkdir()
        self.task_id = self.journal.create("Synthetic create/revise", "alpha", {
            "files": [], "create_files": ["new.txt"], "memory_classes": ["public", "internal"]})
        self.agent = Agent(self.store, CreateProvider())

    def proposal(self, task_id=None):
        task_id = task_id or self.task_id
        current = self.journal.plans.current(task_id)
        steps = copy.deepcopy(current["steps"])
        ordinal = max((s["ordinal"] for s in steps), default=-1) + 1
        steps.append({"action_id": f"{task_id}:{ordinal}", "ordinal": ordinal,
                      "depends_on": [s["action_id"] for s in steps],
                      "request": {"task_id": task_id, "capability_id": "CAP-002",
                                  "operation": "search_memory", "arguments": {"query": "synthetic"}}})
        return {"base_digest": current["digest"], "reason": "synthetic revision", "steps": steps}

    def test_model_in_task_revision_retains_verified_create_without_replay(self):
        class ReviseProvider(CreateProvider):
            revised = False

            def complete(provider, messages, *, task_id):
                reply = super().complete(messages, task_id=task_id)
                if not reply["steps"] and not provider.revised:
                    provider.revised = True
                    reply["revision"] = self.proposal(task_id)
                return reply
        self.agent.model = ReviseProvider()
        waiting = self.agent.run(self.task_id)
        first = waiting["actions"][0]
        self.journal.approve(first["approval_id"], first["digest"])
        result = self.agent.run(self.task_id)
        self.assertEqual(result["task"]["state"], "completed", result)
        self.assertEqual(result["plan"]["revision"], 1)
        self.assertEqual(len(result["actions"]), 2)
        self.assertEqual(result["actions"][0]["id"], first["id"])
        self.assertTrue(all(a["attempts"] == 1 for a in result["actions"]))
        self.assertEqual(self.journal.approval(first["approval_id"])["status"], "consumed")
        self.assertTrue(any(e["kind"] == "plan_revised" for e in result["events"]))
        with Store(self.paths) as store:
            self.assertEqual(Agent(store, CreateProvider()).journal.plans.current(self.task_id)["digest"],
                             result["plan"]["digest"])

    def test_approved_actions_cannot_change_or_disappear_or_reset_approval(self):
        waiting = self.agent.run(self.task_id)
        first = waiting["actions"][0]
        approval = self.journal.approval(first["approval_id"])
        variants = []
        changed = self.proposal()
        changed["steps"][0]["request"]["arguments"]["text"] = "substituted"
        variants.append(changed)
        changed = self.proposal()
        changed["steps"][0]["request"]["arguments"]["path"] = "other.txt"
        variants.append(changed)
        changed = self.proposal()
        changed["steps"] = [changed["steps"][1]]
        changed["steps"][0]["depends_on"] = []
        variants.append(changed)
        for proposal in variants:
            with self.assertRaises(AgentError):
                self.journal.plans.revise(self.task_id, proposal, self.agent.registry)
            self.assertEqual(self.journal.approval(first["approval_id"]), approval)
            self.assertEqual(self.journal.plans.current(self.task_id)["revision"], 0)
        with self.assertRaisesRegex(AgentError, "approval_already_bound"):
            self.journal.request_approval(first["id"])

    def test_dependency_cycles_missing_ids_ordinal_reuse_stale_base_and_limit(self):
        self.agent.run(self.task_id)
        for mutate in (
            lambda p: p["steps"][-1].update(depends_on=["missing"]),
            lambda p: p["steps"][-1].update(depends_on=[p["steps"][-1]["action_id"]]),
            lambda p: p["steps"][-1].update(ordinal=0, action_id=f"{self.task_id}:0"),
            lambda p: p.update(base_digest="0" * 64),
        ):
            proposal = self.proposal()
            mutate(proposal)
            with self.assertRaises(AgentError):
                self.journal.plans.revise(self.task_id, proposal, self.agent.registry)
        for _ in range(3):
            self.journal.plans.revise(self.task_id, self.proposal(), self.agent.registry)
        with self.assertRaisesRegex(AgentError, "plan_revision_budget_exhausted"):
            self.journal.plans.revise(self.task_id, self.proposal(), self.agent.registry)

    def test_revision_cannot_smuggle_second_create_of_prepared_target(self):
        self.agent.run(self.task_id)
        proposal = self.proposal()
        proposal["steps"][-1]["request"] = copy.deepcopy(proposal["steps"][0]["request"])
        with self.assertRaisesRegex(AgentError, "non_idempotent_plan_replay_denied"):
            self.journal.plans.revise(self.task_id, proposal, self.agent.registry)

    def test_prepare_cannot_substitute_unprepared_ordinal(self):
        self.agent.run(self.task_id)
        request = self.journal.plan(self.task_id)[0]
        with self.assertRaisesRegex(AgentError, "action_not_in_current_plan"):
            self.journal.prepare(self.task_id, 99, request, "workspace_write", "forged")

    def test_rejection_of_model_revision_is_visible_without_replaying(self):
        class BadRevision(CreateProvider):
            def complete(provider, messages, *, task_id):
                reply = super().complete(messages, task_id=task_id)
                if not reply["steps"]:
                    reply["revision"] = self.proposal(task_id)
                    reply["revision"]["steps"][0]["request"]["arguments"]["text"] = "changed"
                return reply
        self.agent.model = BadRevision()
        waiting = self.agent.run(self.task_id)
        first = waiting["actions"][0]
        self.journal.approve(first["approval_id"], first["digest"])
        result = self.agent.run(self.task_id)
        self.assertEqual(result["task"]["state"], "blocked")
        self.assertEqual(result["task"]["block_reason"], "immutable_action_changed")
        with patch.object(self.agent, "_tool") as tool:
            self.agent.run(self.task_id, resume=True)
            tool.assert_not_called()
        self.assertEqual(self.journal.action(first["id"])["attempts"], 1)

    def test_cli_revision_and_v1_migration_keep_the_same_pending_approval(self):
        import test_cli
        waiting = self.agent.run(self.task_id)
        first = waiting["actions"][0]
        approval_before = self.journal.approval(first["approval_id"])
        # v1 stores the same original tasks.plan/actions/approvals; only v2's additive table is absent.
        self.store.connection.executescript("DROP TABLE plan_revisions; PRAGMA user_version=1;")
        with Store(self.paths) as upgraded:
            journal = Agent(upgraded, CreateProvider()).journal
            self.assertTrue(journal.plans.current(self.task_id)["legacy"])
            self.assertEqual(journal.approval(first["approval_id"]), approval_before)
        proposal = self.proposal()
        plan_file = self.paths.root / "revision.json"
        plan_file.write_text(json.dumps(proposal), encoding="utf-8")
        reply = test_cli.CliTests.invoke(self, "revise", self.task_id, "--plan", str(plan_file))
        self.assertEqual(reply.returncode, 2, reply.stderr)  # still waiting approval, not false success
        document = json.loads(reply.stdout)
        self.assertEqual(document["plan"]["revision"], 1)
        self.assertEqual(document["actions"][0]["approval_id"], first["approval_id"])
        self.journal.approve(first["approval_id"], first["digest"])
        result = self.agent.run(self.task_id)
        self.assertEqual(result["task"]["state"], "completed", result)
        self.assertEqual(self.journal.action(first["id"])["attempts"], 1)
