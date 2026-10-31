"""Owner-controlled immutable persona versions, outside model and database."""
from __future__ import annotations

import json
import os

from .config import AgentError, Paths, reject_links, specification, validate
from .data_policy import admit
from .storage import Store, encode, now, uid
from .trust import Trust


class Identity:
    def __init__(self, paths: Paths):
        self.paths = paths

    def versions(self) -> list[int]:
        directory = self.paths.directory("identity")
        return sorted(int(p.stem.split("-")[-1]) for p in directory.glob("persona-*.json")
                      if p.stem.split("-")[-1].isdigit())

    def current(self) -> dict:
        versions = self.versions()
        if not versions:
            raise AgentError("persona_not_initialized")
        with Store(self.paths) as store:
            Trust(store).guard("persona", "identity", str(versions[-1]))
        path = self.paths.file("identity", f"persona-{versions[-1]}.json")
        reject_links(path)
        if path.stat().st_size > 12000:
            raise AgentError("persona_size_exceeded")
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            raise AgentError("persona_corrupted") from None
        validate("persona", value)
        admit(value)
        if value["version"] != versions[-1]:
            raise AgentError("persona_version_mismatch")
        with Store(self.paths) as store:
            Trust(store).require("persona", str(value["version"]), "identity", value)
        return value

    def initialize(self):
        if not self.versions():
            value = specification("examples/persona.json")
            value.update(updated_at=now(), provenance="architecture_baseline_default")
            self.save(value)

    def save(self, value: dict):
        """Owner boundary only; no tool can call this. New version or fail, never overwrite."""
        validate("persona", value)
        admit(value)
        previous = self.current() if self.versions() else None
        expected = previous["version"] + 1 if previous else 1
        if (value["version"] != expected
                or value.get("supersedes_version") != (expected - 1 if previous else None)
                or (previous and value["persona_id"] != previous["persona_id"])):
            raise AgentError("persona_version_conflict")
        payload = encode(value)
        with Store(self.paths) as store:
            Trust(store).guard("persona", "identity", str(expected))
        if len(payload.encode("utf-8")) > 12000:
            raise AgentError("persona_size_exceeded")
        final = self.paths.file("identity", f"persona-{expected}.json")
        temporary = self.paths.file("identity", f"pending-{uid()}.json")
        try:
            with temporary.open("x", encoding="utf-8") as output:
                output.write(payload)
                output.flush()
                os.fsync(output.fileno())
            # Windows rename is no-replace; POSIX link publishes without replacing a version.
            if os.name == "nt":
                os.rename(temporary, final)
            else:
                os.link(temporary, final)
            with Store(self.paths) as store:
                Trust(store).attest("persona", str(expected), "identity", value, "internal")
        except FileExistsError:
            raise AgentError("persona_version_conflict") from None
        finally:
            temporary.unlink(missing_ok=True)
