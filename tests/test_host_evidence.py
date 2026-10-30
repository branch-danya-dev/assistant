import hashlib
import json
import sys
from unittest.mock import patch

from support import REPO, RuntimeCase

sys.path.insert(0, str(REPO / "tools"))
from verify_host import verify, verify_model_files  # noqa: E402

from personal_agent.config import AgentError  # noqa: E402


class HostEvidenceTests(RuntimeCase):
    def test_harness_revision_is_not_reported_as_live_model_revision(self):
        class SyntheticProvider:
            metrics = {}

            def smoke(self):
                return {"model": "qwen3.5:9b"}

            def _request(self, *args):
                return {}

            def complete(self, messages, *, task_id):
                context = json.loads(messages[-1]["content"])
                if context["phase"] == "plan":
                    if context["allowed_create_files"]:
                        steps = [{"task_id": task_id, "capability_id": "CAP-008", "operation": "create_text",
                                  "arguments": {"path": "new.txt", "text": "SYNTHETIC-CREATE-42"}}]
                    else:
                        steps = [{"task_id": task_id, "capability_id": cap, "operation": op, "arguments": args}
                                 for cap, op, args in [("CAP-007", "read_text", {"path": "note.txt"}),
                                                       ("CAP-002", "search_memory", {"query": "colour"})]]
                    return {"steps": steps, "answer": "", "evidence_refs": []}
                return {"steps": [], "answer": "LOCAL-42 green", "evidence_refs":
                        [o["evidence_ref"] for o in context["untrusted_observations"]]}
        with patch("verify_host.Ollama", return_value=SyntheticProvider()), \
                patch("verify_host.verify_model_files", return_value={"passed": True}), \
                patch("verify_host.model_storage_status", return_value={"windows_user_value_matches": True}):
            report = verify(str(self.paths.root))
        self.assertTrue(report["passed"], report)
        self.assertTrue(report["checks"]["live_create_with_harness_revision_exactly_once"])
        self.assertEqual(report["revision_provenance"]["actor"], "owner/test-harness")
        self.assertFalse(report["revision_provenance"]["live_model_generated_revision_tested"])
        self.assertIn("source_revision", report)

    def setUp(self):
        super().setUp()
        root = self.paths.directory("models_ollama")
        data = b"synthetic model content"
        digest = hashlib.sha256(data).hexdigest()
        self.blob = root / "blobs" / ("sha256-" + digest)
        self.blob.parent.mkdir()
        self.blob.write_bytes(data)
        manifest = root / "manifests/registry.ollama.ai/library/qwen3.5/9b"
        manifest.parent.mkdir(parents=True)
        raw = json.dumps({"config": {"digest": "sha256:" + digest, "size": len(data)}, "layers": []}).encode()
        manifest.write_bytes(raw)
        self.info = {"modelfile": f'FROM "{self.blob}"'}
        self.status = {"digest": hashlib.sha256(raw).hexdigest()}

    def test_filesystem_hashes_are_independent_of_ollama_report(self):
        report = verify_model_files(self.paths, self.info, self.status)
        self.assertTrue(report["passed"])
        self.assertTrue(report["independent_filesystem"]["blobs"][0]["hash_matches_manifest"])
        self.assertFalse(report["loaded_model_memory_independently_verified"])
        self.blob.write_bytes(b"synthetic model tampered")
        self.assertFalse(verify_model_files(self.paths, self.info, self.status)["passed"])

    def test_reported_prefix_does_not_prove_existence(self):
        self.blob.unlink()
        with self.assertRaises(FileNotFoundError):
            verify_model_files(self.paths, self.info, self.status)

    def test_reported_outside_path_and_wrong_tag_rejected(self):
        other = self.paths.root / "outside-blob"
        other.write_bytes(b"synthetic")
        with self.assertRaisesRegex(AgentError, "model_path_outside_root"):
            verify_model_files(self.paths, {"modelfile": f"FROM {other}"}, self.status)
        self.assertFalse(verify_model_files(self.paths, self.info, {"digest": "0" * 64})["passed"])

    def test_rewritten_manifest_requires_hashed_original_and_identical_active_layers(self):
        root = self.paths.directory("models_ollama")
        manifest = root / "manifests/registry.ollama.ai/library/qwen3.5/9b"
        raw = manifest.read_bytes()
        original = root / "blobs" / ("sha256-" + self.status["digest"])
        original.write_bytes(raw)
        wrapped = json.loads(raw)
        wrapped["layers"].append({"mediaType": "application/vnd.docker.distribution.manifest.v2+json",
                                   "digest": "sha256:" + self.status["digest"], "size": len(raw)})
        manifest.write_text(json.dumps(wrapped), encoding="utf-8")
        report = verify_model_files(self.paths, self.info, self.status)
        self.assertTrue(report["passed"])
        self.assertEqual(report["ollama_report"]["tag_digest_source"], "verified_retained_manifest_blob")
        wrapped["config"]["size"] += 1
        manifest.write_text(json.dumps(wrapped), encoding="utf-8")
        self.assertFalse(verify_model_files(self.paths, self.info, self.status)["passed"])
