"""Offline baseline checks; fixtures never touch real weights or training data.

Run from the repository root: python -m unittest discover -s tests -v
"""
import importlib
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))


class BackendSmokeTests(unittest.TestCase):
    def test_import_from_backend_directory(self):
        result = subprocess.run(
            [sys.executable, "-c", "import app; print(app.app.title)"],
            cwd=ROOT / "backend", capture_output=True, text=True, timeout=60,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_api_and_schema(self):
        from fastapi.testclient import TestClient
        from app import app
        from api.characters import CharacterResponse
        from schemas.model import VoiceModelInfo, VoiceModelListResponse

        with TestClient(app) as client:
            self.assertEqual(client.get("/").status_code, 200)
            self.assertEqual(client.get("/health").json(), {"status": "healthy"})
            self.assertEqual(client.get("/health").status_code, 200)
            spec = client.get("/openapi.json")
            self.assertEqual(spec.status_code, 200)
            paths = spec.json()["paths"]
            for path in ("/api/characters", "/api/voices/upload", "/api/transcriptions",
                         "/api/training/start", "/api/datasets/build", "/api/models",
                         "/api/models/refresh", "/api/models/{model_id}"):
                self.assertIn(path, paths)
            characters = client.get("/api/characters")
            self.assertEqual(characters.status_code, 200, characters.text)
            for character in characters.json():
                CharacterResponse.model_validate(character)
            response = client.get("/api/models")
            self.assertEqual(response.status_code, 200, response.text)
            listing = VoiceModelListResponse.model_validate(response.json())
            self.assertEqual(listing.total, len(listing.models))
            self.assertEqual(len({m.id for m in listing.models}), listing.total)
            for model in listing.models:
                detail = client.get(f"/api/models/{model.id}")
                self.assertEqual(detail.status_code, 200, detail.text)
                self.assertEqual(VoiceModelInfo.model_validate(detail.json()), model)
            self.assertEqual(client.get("/api/models/missing-id").status_code, 404)

    def test_refresh_route_is_reachable(self):
        from fastapi.testclient import TestClient
        from app import app
        from api.models import get_model_service
        from schemas.model import VoiceModelListResponse
        with TestClient(app) as client:
            response = client.get("/api/models/refresh")
            self.assertEqual(response.status_code, 200, response.text)
            VoiceModelListResponse.model_validate(response.json())
        get_model_service.cache_clear()

    def test_pairing_selection_ids_and_missing_weights(self):
        from services.model_service import ModelService
        from schemas.model import VoiceModelListResponse
        from fastapi.testclient import TestClient
        from app import app
        from api.models import get_model_service

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            gpt, sovits = root / "gpt", root / "sovits"
            service = ModelService(root, gpt, sovits)
            self.assertEqual(service.list_models(), [])
            gpt.mkdir()
            sovits.mkdir()
            self.assertEqual(service.list_models(), [])
            for name in ("actor_japanese_1234abcd-e5.ckpt", "actor_japanese_1234abcd-e15.ckpt",
                         "gpt_only-e1.ckpt"):
                (gpt / name).touch()
            for name in ("actor_japanese_1234abcd_e4_s200.pth",
                         "actor_japanese_1234abcd_e8_s400.pth", "sovits_only_e1_s1.pth"):
                (sovits / name).touch()
            models = service.list_models()
            self.assertEqual(len(models), 3)
            ready = service.get_model("1234ABCD")
            self.assertEqual(ready.status, "ready")
            self.assertEqual(ready.language, "ja")
            self.assertTrue(ready.gpt.endswith("-e15.ckpt"))
            self.assertTrue(ready.sovits.endswith("_e8_s400.pth"))
            self.assertEqual(sum(m.status == "incomplete" for m in models), 2)
            ids = [m.id for m in models]
            self.assertEqual(ids, [m.id for m in service.list_models()])
            self.assertIsNone(service.get_model("missing"))
            # Patch only discovery dependency; requests still exercise response validation.
            with patch("api.models.get_model_service", return_value=service):
                with TestClient(app) as client:
                    response = client.get("/api/models")
                    self.assertEqual(response.status_code, 200)
                    parsed = VoiceModelListResponse.model_validate(response.json())
                    self.assertEqual(parsed.total, 3)
                    for model in parsed.models:
                        self.assertEqual(client.get(f"/api/models/{model.id}").status_code, 200)
            (sovits / "actor_japanese_1234abcd_e4_s200.pth").unlink()
            (sovits / "actor_japanese_1234abcd_e8_s400.pth").unlink()
            self.assertEqual(service.get_model("1234abcd").status, "incomplete")
            self.assertIsNone(service.get_model("1234abcd").sovits)
        get_model_service.cache_clear()

    def test_all_backend_modules_import(self):
        for directory in ("api", "services", "schemas", "workers"):
            for file in (ROOT / "backend" / directory).glob("*.py"):
                if file.stem != "__init__":
                    with self.subTest(module=f"{directory}.{file.stem}"):
                        importlib.import_module(f"{directory}.{file.stem}")


if __name__ == "__main__":
    unittest.main()
