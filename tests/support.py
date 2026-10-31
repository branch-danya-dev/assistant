import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from personal_agent.config import Paths  # noqa: E402
from personal_agent.journal import Journal  # noqa: E402
from personal_agent.storage import Store  # noqa: E402


class RuntimeCase(unittest.TestCase):
    def setUp(self):
        # Explicit sibling root: no runtime data in Git, no default C: temp on Windows.
        temp_parent = REPO.parent / "test-runs"
        temp_parent.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=temp_parent)
        self.paths = Paths(Path(self.temp.name) / "home")
        self.paths.bootstrap()
        self.store = Store(self.paths)
        self.journal = Journal(self.store)

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def task(self, *, project="alpha", budget=None, files=None, private=False):
        return self.journal.create("Synthetic test", project,
                                   {"files": files or [], "memory_classes":
                                    ["public", "internal", *(["private"] if private else [])]},
                                   budget=budget)

    def action(self, effect="read"):
        task = self.task()
        self.journal.start(task)
        request = dict(task_id=task, capability_id="CAP-007", operation="read_text",
                       arguments={"path": "fixture.txt"})
        self.journal.set_plan(task, [request])
        action = self.journal.prepare(task, 0, request, effect, "workspace/alpha/fixture.txt")
        return task, action, request

    def legacy_restricted_memory(self, project, text, source):
        """Historical synthetic row: v4 never admits new restricted source bytes."""
        from personal_agent.memory import Memory
        from personal_agent.storage import encode
        identifier = Memory(self.store).remember(project, text, source, sensitivity="internal")
        record = json.loads(self.store.connection.execute(
            "SELECT document FROM memory WHERE id=?", (identifier,)).fetchone()[0])
        record["sensitivity"] = "restricted"
        self.store.connection.execute("UPDATE memory SET sensitivity='restricted',document=? WHERE id=?",
                                      (encode(record), identifier))
        self.store.connection.execute("DELETE FROM data_admissions WHERE object_id=?", (identifier,))
        return identifier
