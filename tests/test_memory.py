from support import RuntimeCase

from personal_agent.config import AgentError
from personal_agent.identity import Identity
from personal_agent.memory import Memory
from personal_agent.storage import Store, now


class MemoryTests(RuntimeCase):
    def setUp(self):
        super().setUp()
        self.memory = Memory(self.store)

    def test_scn004_restart_sources_and_supersession(self):
        previous = self.memory.remember("alpha", "Use blue", "fixture://old", sensitivity="internal")
        latest = self.memory.remember("alpha", "Use green", "fixture://new", sensitivity="internal",
                                      supersedes=[previous])
        self.memory.remember("beta", "Use secret", "fixture://other", sensitivity="private")
        with Store(self.paths) as reopened:
            results = Memory(reopened).search("Use", project_id="alpha")
        self.assertEqual([r["id"] for r in results], [latest, previous])
        self.assertEqual(results[0]["source_refs"], ["fixture://new"])
        self.assertEqual(results[1]["superseded_by"], [latest])

    def test_scope_before_ranking(self):
        self.memory.remember("alpha", "public needle", "fixture://a", sensitivity="public")
        self.memory.remember("alpha", "private needle", "fixture://b", sensitivity="private")
        with self.assertRaises(AgentError):
            self.memory.remember("alpha", "restricted needle", "fixture://c", sensitivity="restricted")
        self.legacy_restricted_memory("alpha", "restricted needle", "fixture://c")
        self.memory.remember("beta", "secret needle", "fixture://d", sensitivity="private")
        self.assertEqual(len(self.memory.search("needle OR beta", project_id="alpha")), 1)
        self.assertEqual(len(self.memory.search("needle", project_id="alpha",
                                               allowed_classes=("private",))), 1)
        with self.assertRaises(AgentError):
            self.memory.search("needle", project_id=None)
        with self.assertRaises(AgentError):
            self.memory.search("needle", project_id="alpha", allowed_classes=("restricted",))

    def test_unverified_or_cross_scope_supersession_denied(self):
        first = self.memory.remember("alpha", "Verified", "fixture://owner", evidence_status="verified")
        with self.assertRaises(AgentError):
            self.memory.remember("alpha", "Guess", "fixture://model", supersedes=[first])
        with self.assertRaises(AgentError):
            self.memory.remember("beta", "Cross", "fixture://owner", supersedes=[first],
                                 evidence_status="verified")

    def test_retention_and_rebuild(self):
        durable = self.memory.remember("alpha", "durable needle", "fixture://owner", sensitivity="internal")
        self.memory.add(dict(id="expired", project_id="alpha", kind="fact", statement="temp needle",
                             source_refs=["fixture://cache"], evidence_status="observed", recorded_at=now(),
                             supersedes=[], sensitivity="internal", retention_class="temporary",
                             expires_at="2000-01-01T00:00:00Z"))
        before = self.memory.search("needle", project_id="alpha")
        self.memory.rebuild_index()
        self.assertEqual(self.memory.search("needle", project_id="alpha"), before)
        self.assertEqual([r["id"] for r in before], [durable])
        self.memory.remove_from_retrieval(durable, project_id="alpha")
        self.memory.rebuild_index()
        self.assertEqual(self.memory.search("needle", project_id="alpha"), [])
        self.assertEqual(self.store.connection.execute("SELECT count(*) FROM memory").fetchone()[0], 2)

    def test_scn011_versioned_identity_restart(self):
        identity = Identity(self.paths)
        identity.initialize()
        initial = identity.current()
        updated = {**initial, "version": 2, "supersedes_version": 1,
                   "preferences": {"answer_length": "detailed"}, "provenance": "fixture://owner"}
        identity.save(updated)
        self.assertEqual(Identity(self.paths).current(), updated)
        self.assertEqual(identity.versions(), [1, 2])
        with self.assertRaises(AgentError):
            identity.save(updated)
        self.assertTrue(self.paths.file("identity", "persona-1.json").is_file())
