"""Opt-in live Qwen acceptance using synthetic data only; never download/switch a model."""
import argparse
import hashlib
import json
import os
import re
import stat
import subprocess
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


def source_revision():
    """Record the exact checkout; a dirty tree is never evidence for its HEAD alone."""
    repository = Path(__file__).resolve().parents[1]
    try:
        commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repository,
                                         text=True, stderr=subprocess.DEVNULL).strip()
        status = subprocess.check_output(["git", "status", "--porcelain"], cwd=repository,
                                         text=True, stderr=subprocess.DEVNULL).strip()
        return {"commit": commit, "dirty": bool(status)}
    except (OSError, subprocess.CalledProcessError):
        return {"commit": None, "dirty": None}


def runtime_fingerprint():
    repository = Path(__file__).resolve().parents[1]
    files = [*repository.glob("src/personal_agent/*.py"),
             *repository.glob("spec/schemas/*.json"),
             repository / "spec/model-config.json", repository / "spec/storage-config.json",
             Path(__file__).resolve()]
    digest = hashlib.sha256()
    for file in sorted(files):
        # Git can check out CRLF on Windows: hash canonical UTF-8 text for reproducibility.
        digest.update(file.relative_to(repository).as_posix().encode() + b"\0"
                      + file.read_text(encoding="utf-8").encode("utf-8") + b"\0")
    return digest.hexdigest()


def verify_model_files(paths, info, status, *, hash_files=True):
    """Separate Ollama assertions from filesystem observations; no inference from prefix alone."""
    expected = paths.directory("models_ollama")
    reject_links(expected)
    root = expected.resolve(strict=True)
    manifest_directory = root / "manifests/registry.ollama.ai/library/qwen3.5"
    end = time.monotonic() + 300

    def inspect(path, expected_digest=None, expected_size=None, *, is_manifest=False):
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
            if hash_files or is_manifest:
                while chunk := os.read(fd, 1024 * 1024):
                    if time.monotonic() >= end:
                        raise AgentError("model_hash_timeout")
                    h.update(chunk)
                    if is_manifest:
                        data.extend(chunk)
                        if len(data) > 1048576:
                            raise AgentError("model_manifest_too_large")
            after = os.fstat(fd)
            if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                raise AgentError("model_file_changed")
            digest = h.hexdigest() if hash_files or is_manifest else None
            return {"path": actual.relative_to(root).as_posix(), "exists": True,
                    "canonical_containment": True, "bytes": before.st_size,
                    "size_matches_manifest": expected_size is None or before.st_size == expected_size,
                    "sha256": digest, "hash_matches_manifest":
                    digest == expected_digest if expected_digest and hash_files else None}, bytes(data)
        finally:
            os.close(fd)

    # Ollama may resolve the selected 9b alias to a quantization-tag manifest. Match the
    # selected runtime digest against files of this same model; never choose another model.
    reject_links(manifest_directory)
    candidates = sorted(p for p in manifest_directory.iterdir()
                        if p.name == "9b" or p.name.startswith("9b-"))
    if not candidates or len(candidates) > 32:
        raise AgentError("selected_manifest_missing_or_ambiguous")
    matched = []
    selected_digest = status.get("digest", "").removeprefix("sha256:")
    if not re.fullmatch(r"[a-f0-9]{64}", selected_digest):
        raise AgentError("invalid_selected_model_digest")
    for candidate in candidates:
        check, data = inspect(candidate, is_manifest=True)
        if check["sha256"] == selected_digest:
            matched.append((check, data, "named_manifest_file"))
            continue
        current = json.loads(data)
        retained = [layer for layer in current.get("layers", [])
                    if layer.get("mediaType") == "application/vnd.docker.distribution.manifest.v2+json"
                    and layer.get("digest") == "sha256:" + selected_digest]
        if retained:
            # New Ollama versions retain the original manifest as a blob when rewriting its
            # named representation. Verify that blob AND its agreement with active layers.
            original_check, original_data = inspect(root / "blobs" / ("sha256-" + selected_digest),
                selected_digest, retained[0]["size"], is_manifest=True)
            original = json.loads(original_data)
            effective = [layer for layer in current["layers"] if layer not in retained]
            if (original_check["sha256"] == selected_digest
                    and original_check["size_matches_manifest"]
                    and original.get("config") == current.get("config")
                    and original.get("layers") == effective):
                matched.append((check, data, "verified_retained_manifest_blob"))
    if not matched:
        return {"passed": False, "ollama_report": {"tag_digest_matches_manifest": False},
                "independent_filesystem": {"candidate_manifest_count": len(candidates)},
                "loaded_model_memory_independently_verified": False}
    manifest_check, raw, digest_source = matched[0]
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
    tag_matches = True  # The selected digest and all active-layer agreement were checked above.
    passed = (bool(blobs) and reported_matches and tag_matches
              and all(b["size_matches_manifest"] for b in blobs)
              and (not hash_files or all(b["hash_matches_manifest"] for b in blobs)))
    return {"passed": passed,
            "ollama_report": {"from_count": len(reported), "from_matches_manifest": reported_matches,
                              "tag_digest_matches_manifest": tag_matches, "tag_digest_source": digest_source},
            "independent_filesystem": {"manifest": manifest_check, "blobs": blobs,
                                       "hashes_checked": hash_files},
            "running_process_environment_verified": False,
            "loaded_model_memory_independently_verified": False}


def verify(root: str) -> dict:
    owner_paths = Paths(root)
    owner_paths.require()
    model = Ollama(timeout=120)
    smoke = model.smoke()
    info = model._request("/api/show", {"model": "qwen3.5:9b"})
    storage = verify_model_files(owner_paths, info, smoke)
    # Never migrate or mix acceptance data into the owner's real task/memory database.
    paths = Paths(owner_paths.directory("cache") / ("host-acceptance-" + uid()))
    paths.bootstrap()
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
    # A second live task creates an exact synthetic file. Opt-in to this harness authorizes
    # only this fixture payload; an unexpected model proposal is never automatically approved.
    with Store(paths) as store:
        journal = Journal(store)
        create_task = journal.create(
            'Use create_text to create exactly new.txt with text "SYNTHETIC-CREATE-42". '
            'Do not add a newline. Then report saved evidence.', project,
            {"files": [], "create_files": ["new.txt"], "memory_classes": ["public", "internal"]})
        agent = Agent(store, model)
        waiting = agent.run(create_task)
        expected = {"task_id": create_task, "capability_id": "CAP-008", "operation": "create_text",
                    "arguments": {"path": "new.txt", "text": "SYNTHETIC-CREATE-42"}}
        create_result = waiting
        if (waiting["task"]["state"] == "waiting_approval" and len(waiting["actions"]) == 1
                and journal.plan(create_task) == [expected]):
            action = waiting["actions"][0]
            current = journal.plans.current(create_task)
            # OWNER/TEST-HARNESS injected revision, NOT a model-generated revision.
            # Real Qwen handles planning/final responses; this line must not certify model revision.
            proposal = {"base_digest": current["digest"], "reason": "Synthetic live acceptance revision",
                        "steps": [*current["steps"], {"ordinal": 1, "action_id": f"{create_task}:1",
                            "depends_on": [f"{create_task}:0"], "request": {
                                "task_id": create_task, "capability_id": "CAP-002",
                                "operation": "search_memory", "arguments": {"query": "colour"}}}]}
            journal.plans.revise(create_task, proposal, agent.registry)
            journal.approve(action["approval_id"], action["digest"])
            create_result = agent.run(create_task)
            create_verified = (create_result["task"]["state"] == "completed"
                               and journal.action(action["id"])["attempts"] == 1
                               and journal.approval(action["approval_id"])["status"] == "consumed"
                               and (workspace / "new.txt").read_text() == "SYNTHETIC-CREATE-42")
        else:
            create_verified = False
    checks = {"local_task_completed": result["task"]["state"] == "completed",
              "both_read_tools_verified": operations == {"read_text", "search_memory"},
              "expected_answer": "LOCAL-42" in answer and "green" in answer.lower(),
              "memory_restart_and_history": {r["id"] for r in records} == {old, latest},
              "persona_restart": identity_survived, "journal_restart": task_survived,
              "windows_user_model_path": model_storage_status(owner_paths)["windows_user_value_matches"],
              "actual_model_files_on_root": storage["passed"],
              "live_create_with_harness_revision_exactly_once": create_verified}
    return {"timestamp": now(), "synthetic_only": True, "selected_model": smoke,
            "source_revision": source_revision(),
            "revision_provenance": {
                "actor": "owner/test-harness", "injected_by": "tools/verify_host.py",
                "live_model_generated_revision_tested": False,
                "synthetic_model_revision_tests": "tests/test_plan_revisions.py; tests/test_context.py",
                "live_model_roles": ["initial_planning", "final_response"]},
            "runtime_source_fingerprint": runtime_fingerprint(),
            "checks": checks, "passed": all(checks.values()), "task_id": task_id,
            "task_state": result["task"]["state"], "block_reason": result["task"]["block_reason"],
            "verified_operations": sorted(operations), "model_comparisons": 0,
            "model_storage_evidence": storage, "isolated_runtime": True,
            "runtime_relative": paths.root.relative_to(owner_paths.root).as_posix(),
            "create_task_state": create_result["task"]["state"],
            "create_block_reason": create_result["task"]["block_reason"]}


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
