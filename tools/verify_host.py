"""Opt-in live Qwen acceptance using synthetic data only; never download/switch a model."""
import argparse
import hashlib
import json
import os
import re
import stat
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from personal_agent.cli import model_storage_status
from personal_agent.config import AgentError, Paths, reject_links
from personal_agent.identity import Identity
from personal_agent.journal import Journal
from personal_agent.memory import Memory
from personal_agent.models import Ollama
from personal_agent.orchestrator import Agent
from personal_agent.safe_fs import opened_path
from personal_agent.storage import Store, now, uid


def verify_model_files(paths, info, status, *, hash_files=True):
    """Separate Ollama assertions from filesystem observations; no inference from prefix alone."""
    expected = paths.directory("models_ollama")
    reject_links(expected)
    root = expected.resolve(strict=True)
    manifest = root / "manifests/registry.ollama.ai/library/qwen3.5/9b"
    end = time.monotonic() + 300

    def inspect(path, expected_digest=None, expected_size=None):
        reject_links(path)
        actual = path.resolve(strict=True)
        if not actual.is_relative_to(root):
            raise AgentError("model_path_outside_root")
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(actual, flags)
        try:
            before = os.fstat(fd)
            if opened_path(fd) != actual or not opened_path(fd).is_relative_to(root):
                raise AgentError("opened_model_path_outside_root")
            if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1
                    or getattr(before, "st_file_attributes", 0) & 0x400):
                raise AgentError("model_file_not_regular")
            # Opened object must still be the independently resolved object.
            if (before.st_dev, before.st_ino) != (actual.stat().st_dev, actual.stat().st_ino):
                raise AgentError("model_path_changed")
            h = hashlib.sha256()
            data = bytearray()
            if hash_files or path == manifest:
                while chunk := os.read(fd, 1024 * 1024):
                    if time.monotonic() >= end:
                        raise AgentError("model_hash_timeout")
                    h.update(chunk)
                    if path == manifest:
                        data.extend(chunk)
                        if len(data) > 1048576:
                            raise AgentError("model_manifest_too_large")
            after = os.fstat(fd)
            if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                raise AgentError("model_file_changed")
            digest = h.hexdigest() if hash_files or path == manifest else None
            return {"path": actual.relative_to(root).as_posix(), "exists": True,
                    "canonical_containment": True, "bytes": before.st_size,
                    "size_matches_manifest": expected_size is None or before.st_size == expected_size,
                    "sha256": digest, "hash_matches_manifest":
                    digest == expected_digest if expected_digest and hash_files else None}, bytes(data)
        finally:
            os.close(fd)

    manifest_check, raw = inspect(manifest)
    document = json.loads(raw)
    records = [document["config"], *document["layers"]]
    blobs = []
    for record in records:
        if not re.fullmatch(r"sha256:[a-f0-9]{64}", record["digest"]):
            raise AgentError("invalid_model_manifest_digest")
        blob, _ = inspect(root / "blobs" / record["digest"].replace(":", "-"),
                          record["digest"][7:], record["size"])
        blobs.append(blob)
    reported = [Path(line[5:].strip().strip('"')) for line in info.get("modelfile", "").splitlines()
                if line.startswith("FROM ")]
    reported_matches = bool(reported)
    for path in reported:
        if not path.is_absolute():
            reported_matches = False
            continue
        entry, _ = inspect(path)
        reported_matches &= entry["path"] in {b["path"] for b in blobs}
    tag_matches = status.get("digest", "").removeprefix("sha256:") == manifest_check["sha256"]
    passed = (bool(blobs) and reported_matches and tag_matches
              and all(b["size_matches_manifest"] for b in blobs)
              and (not hash_files or all(b["hash_matches_manifest"] for b in blobs)))
    return {"passed": passed,
            "ollama_report": {"from_count": len(reported), "from_matches_manifest": reported_matches,
                              "tag_digest_matches_manifest": tag_matches},
            "independent_filesystem": {"manifest": manifest_check, "blobs": blobs,
                                       "hashes_checked": hash_files},
            "running_process_environment_verified": False,
            "loaded_model_memory_independently_verified": False}


def verify(root: str) -> dict:
    paths = Paths(root)
    paths.bootstrap()
    model = Ollama(timeout=120)
    smoke = model.smoke()
    info = model._request("/api/show", {"model": "qwen3.5:9b"})
    storage = verify_model_files(paths, info, smoke)
    project = "host-check-" + uid()[:8]
    workspace = paths.project_workspace(project)
    workspace.mkdir()
    (workspace / "note.txt").write_text("Synthetic acceptance fixture. Reference code: LOCAL-42.", encoding="utf-8")
    with Store(paths) as store, store.execution_lock():
        Identity(paths).initialize()
        persona = Identity(paths).current()
        memory = Memory(store)
        old = memory.remember(project, "The project colour is blue", "fixture://original",
                              sensitivity="internal", evidence_status="verified")
        latest = memory.remember(project, "The project colour is green", "fixture://replacement",
                                 sensitivity="internal", evidence_status="verified", supersedes=[old])
        task_id = Journal(store).create(
            'Execute both read_text for note.txt and search_memory for query "colour". '
            'Then report the reference code and the latest colour decision. Read-only.', project,
            {"files": ["note.txt"], "memory_classes": ["public", "internal"]})
    with Store(paths) as store:
        result = Agent(store, model).run(task_id)
    with Store(paths) as store:
        records = Memory(store).search("colour", project_id=project)
        identity_survived = Identity(paths).current() == persona
        task_survived = Journal(store).get(task_id)["state"] == result["task"]["state"]
    actions = result["actions"]
    operations = {a["request"]["operation"] for a in actions if a["status"] == "verified"}
    answer = (result["result"] or {}).get("answer", "")
    checks = {"local_task_completed": result["task"]["state"] == "completed",
              "both_read_tools_verified": operations == {"read_text", "search_memory"},
              "expected_answer": "LOCAL-42" in answer and "green" in answer.lower(),
              "memory_restart_and_history": {r["id"] for r in records} == {old, latest},
              "persona_restart": identity_survived, "journal_restart": task_survived,
              "windows_user_model_path": model_storage_status(paths)["windows_user_value_matches"],
              "actual_model_files_on_root": storage["passed"]}
    return {"timestamp": now(), "synthetic_only": True, "selected_model": smoke,
            "checks": checks, "passed": all(checks.values()), "task_id": task_id,
            "task_state": result["task"]["state"], "block_reason": result["task"]["block_reason"],
            "verified_operations": sorted(operations), "model_comparisons": 0,
            "model_storage_evidence": storage}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True, help="Explicit test target; creates a synthetic project")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = verify(args.root)
    text = json.dumps(report, indent=2)
    if args.output:
        args.output.write_text(text + "\n", encoding="utf-8")
    print(text)
    raise SystemExit(0 if report["passed"] else 2)
