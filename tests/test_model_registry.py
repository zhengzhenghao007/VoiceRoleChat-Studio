"""Model registry regressions using disposable files, never real checkpoints."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from services.model_service import ModelService


class ModelRegistryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.service = ModelService(self.root)
        self.gpt = self.root / "GPT-SoVITS/GPT_weights_v2Pro"
        self.sovits = self.root / "GPT-SoVITS/SoVITS_weights_v2Pro"

    def weight(self, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
        return path

    def training(self, experiment="actor_1234abcd"):
        return (self.weight(self.gpt / f"{experiment}-e15.ckpt"),
                self.weight(self.sovits / f"{experiment}_e8_s400.pth"))

    def export(self, job="job1", experiment="actor_1234abcd", sources=None):
        directory = self.root / "models" / job
        gpt = self.weight(directory / "gpt_v2pro.ckpt")
        sovits = self.weight(directory / "sovits_v2pro.pth")
        data = {"job_id": job, "experiment_name": experiment, "version": "v2Pro",
                "language": "ja", "gpt_model": str(gpt), "sovits_model": str(sovits)}
        if sources:
            data.update(source_gpt_model=str(sources[0]), source_sovits_model=str(sources[1]))
        path = directory / "manifest.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        return path, data

    def write(self, path, data):
        path.write_text(json.dumps(data), encoding="utf-8")

    def test_collision_unique_stable_ids_and_ambiguous_api(self):
        self.training("one_deadbeef")
        self.training("two_deadbeef")
        models = self.service.list_models()
        self.assertEqual(len({m.id for m in models}), 2)
        self.assertTrue(all(m.id.startswith("deadbeef-") for m in models))
        for model in models:
            self.assertEqual(self.service.get_model(model.id.upper()).name, model.name)
        ids = {m.name: m.id for m in models}
        self.training("unrelated_1234abcd")
        self.assertEqual(ids, {m.name: m.id for m in self.service.list_models() if m.name in ids})
        from app import app
        from fastapi.testclient import TestClient
        with patch("api.models.get_model_service", return_value=self.service):
            with TestClient(app) as client:
                response = client.get("/api/models/DEADBEEF")
                self.assertEqual(response.status_code, 409, response.text)
                self.assertEqual(client.get("/api/models/no-such-model").status_code, 404)
                for model in models:
                    self.assertEqual(client.get(f"/api/models/{model.id}").status_code, 200)

    def test_legacy_ids_unchanged(self):
        self.training("test_character_auto_v3_80a9a003")
        self.training("test_character_japanese_v1")
        self.assertEqual({m.id for m in self.service.list_models()}, {"80a9a003", "2ff64c64"})

    def test_export_only_and_missing_weight(self):
        path, data = self.export()
        models = self.service.list_models()
        self.assertEqual(len(models), 1)
        model = models[0]
        self.assertEqual((model.id, model.language, model.status), ("1234abcd", "ja", "ready"))
        self.assertEqual(model.gpt, "models/job1/gpt_v2pro.ckpt")
        Path(data["sovits_model"]).unlink()
        model = self.service.list_models()[0]
        self.assertEqual(model.status, "incomplete")
        self.assertIsNone(model.sovits)
        Path(data["gpt_model"]).unlink()
        self.assertEqual(self.service.list_models(), [])

    def test_verified_source_dedup_preserves_training_response(self):
        sources = self.training()
        before = self.service.list_models()[0].model_dump()
        self.export(sources=sources)
        self.assertEqual([m.model_dump() for m in self.service.list_models()], [before])

    def test_name_or_short_id_alone_never_merges_models(self):
        self.training()
        self.export()
        self.export(job="job2")
        models = self.service.list_models()
        self.assertEqual(len(models), 3)
        self.assertEqual(len({m.id for m in models}), 3)

    def test_wrong_sources_never_merge_by_experiment_name(self):
        self.training()
        other = self.training("other_87654321")
        self.export(sources=other)
        self.assertEqual(len(self.service.list_models()), 3)

    def test_relative_export_paths(self):
        path, data = self.export()
        data.update(gpt_model="gpt_v2pro.ckpt", sovits_model="models/job1/sovits_v2pro.pth")
        self.write(path, data)
        self.assertEqual(self.service.list_models()[0].status, "ready")

    def test_windows_absolute_relocation(self):
        path, data = self.export()
        data.update(gpt_model=r"Z:\old\VoiceRoleChat-Studio\models\job1\gpt_v2pro.ckpt",
                    sovits_model=r"Z:\old\VoiceRoleChat-Studio\models\job1\sovits_v2pro.pth")
        self.write(path, data)
        self.assertEqual(self.service.list_models()[0].status, "ready")

    def test_invalid_manifest_does_not_break_other_models(self):
        self.training()
        path, data = self.export()
        invalid = [[], {**data, "job_id": "wrong"}, {**data, "gpt_model": 123},
                   {**data, "experiment_name": ""}, {**data, "language": []}]
        for payload in invalid:
            with self.subTest(payload=payload):
                self.write(path, payload)
                with self.assertLogs("services.model_service", level="WARNING"):
                    self.assertEqual(len(self.service.list_models()), 1)
        path.write_text("{invalid", encoding="utf-8")
        with self.assertLogs("services.model_service", level="WARNING"):
            self.assertEqual(len(self.service.list_models()), 1)
        path.write_bytes(b"x" * (1024 * 1024 + 1))
        with self.assertLogs("services.model_service", level="WARNING"):
            self.assertEqual(len(self.service.list_models()), 1)

    def test_unsafe_paths_rejected(self):
        path, data = self.export()
        outside = self.weight(self.root / "outside.ckpt")
        for value in (str(outside), "../outside.ckpt", "models/job1/../job1/gpt_v2pro.ckpt",
                      r"Z:\outside\model.ckpt", "gpt_v2pro.txt"):
            with self.subTest(value=value):
                self.write(path, {**data, "gpt_model": value})
                self.assertEqual(self.service.list_models(), [])

    def test_symlink_escape_rejected(self):
        path, data = self.export()
        target = self.weight(self.root / "outside.ckpt")
        link = path.parent / "link.ckpt"
        try:
            link.symlink_to(target)
        except OSError as error:
            self.skipTest(f"OS disallows symlink creation: {error}")
        self.write(path, {**data, "gpt_model": str(link)})
        self.assertEqual(self.service.list_models(), [])

    def test_resolved_escape_rejected_without_symlink_privilege(self):
        path, data = self.export()
        weight = Path(data["gpt_model"])
        target = self.weight(self.root / "outside.ckpt")
        original_resolve = Path.resolve

        def redirected_resolve(candidate, *args, **kwargs):
            if candidate == weight:
                return target
            return original_resolve(candidate, *args, **kwargs)

        # Exercise the resolved-path boundary on systems that cannot create
        # symlinks. The separate OS-level test remains explicitly skippable.
        with patch.object(Path, "resolve", redirected_resolve):
            self.assertEqual(self.service.list_models(), [])

    def test_relocated_sources_deduplicate(self):
        sources = self.training()
        path, data = self.export(sources=sources)
        for key, source in zip(("source_gpt_model", "source_sovits_model"), sources):
            relative = source.relative_to(self.root).as_posix().replace("/", "\\")
            data[key] = "Z:\\old\\" + self.root.name + "\\" + relative
        self.write(path, data)
        self.assertEqual(len(self.service.list_models()), 1)
        self.assertEqual(self.service.list_models()[0].gpt, sources[0].relative_to(self.root).as_posix())

    def test_refresh_and_list_are_deterministic(self):
        self.export()
        from app import app
        from api.models import get_model_service
        from fastapi.testclient import TestClient
        get_model_service.cache_clear()
        self.addCleanup(get_model_service.cache_clear)
        with patch("api.models.find_project_root", return_value=self.root):
            with TestClient(app) as client:
                first = client.get("/api/models").json()
                self.assertEqual(first["total"], 1)
                self.assertEqual(client.get("/api/models/refresh").json(), first)


if __name__ == "__main__":
    unittest.main()
