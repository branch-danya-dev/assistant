"""Deterministic offline demonstration, explicitly not an Ollama acceptance test."""
import json

from .identity import Identity
from .journal import Journal
from .memory import Memory
from .orchestrator import Agent
from .storage import Store, uid


class DemoProvider:
    def complete(self, messages, *, task_id):
        context = json.loads(messages[-1]["content"])
        if context["phase"] == "plan":
            return {"steps": [
                {"task_id": task_id, "capability_id": "CAP-007", "operation": "read_text",
                 "arguments": {"path": "note.txt"}},
                {"task_id": task_id, "capability_id": "CAP-002", "operation": "search_memory",
                 "arguments": {"query": "Use"}}], "answer": "", "evidence_refs": []}
        observations = context["untrusted_observations"]
        records = observations[1]["output"]["records"]
        return {"steps": [], "answer": "Offline fixture: " + observations[0]["output"]["text"]
                + " Latest sourced decision: " + records[0]["statement"],
                "evidence_refs": [o["evidence_ref"] for o in observations]}


def run_demo(paths):
    paths.bootstrap()
    project = "demo-" + uid()[:8]
    base = paths.project_workspace(project)
    base.mkdir()
    (base / "note.txt").write_text("Synthetic project note.", encoding="utf-8")
    with Store(paths) as store, store.execution_lock():
        Identity(paths).initialize()
        memory = Memory(store)
        old = memory.remember(project, "Use blue", "fixture://original", sensitivity="internal")
        memory.remember(project, "Use green", "fixture://replacement", sensitivity="internal",
                        supersedes=[old])
        task_id = Journal(store).create("Read note and recall Use decision", project,
                                       {"files": ["note.txt"], "memory_classes": ["public", "internal"]})
    # Reopen canonical storage to demonstrate persistence rather than cached Python objects.
    with Store(paths) as reopened:
        result = Agent(reopened, DemoProvider()).run(task_id)
    return {"mode": "offline_fixture_no_model", **result}
