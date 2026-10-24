"""Character API with real temporary storage and isolated fake synthesis upstream."""
from pathlib import Path
import sys
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from fastapi.testclient import TestClient
from app import app
from api.characters import get_character_service
from api.tts import get_synthesis_service
from api.models import get_model_service
from services.character_service import CharacterService
import test_synthesis as fixtures


class CharacterAPITests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.SynthesisTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.store = CharacterService(self.fixture.root / "characters", voice_validator=self.fixture.service.validate_voice)
        app.dependency_overrides[get_character_service] = lambda: self.store
        app.dependency_overrides[get_synthesis_service] = lambda: self.fixture.service
        self.addCleanup(app.dependency_overrides.clear)
        self.client = TestClient(app)
        self.addCleanup(self.client.close)
        self.voice = {key: value for key, value in self.fixture.payload.items() if key != "text"}

    def create(self, **values):
        response = self.client.post("/api/characters", json={"name": "Actor", "system_prompt": "Be kind"} | values)
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def test_create_edit_list_detail_and_conflict(self):
        role = self.create()
        self.assertEqual(role["revision"], 1)
        response = self.client.patch("/api/characters/" + role["id"], json={"name": "Edited", "expected_revision": 1})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["revision"], 2)
        self.assertEqual(self.client.get("/api/characters/" + role["id"]).json(), response.json())
        self.assertEqual(self.client.get("/api/characters").json(), [response.json()])
        self.assertEqual(self.client.patch("/api/characters/" + role["id"],
            json={"name": "Stale", "expected_revision": 1}).status_code, 409)

    def test_bind_without_inference_then_synthesize_and_clear(self):
        self.fixture.manager._process = None
        with patch.object(self.fixture.manager, "inference_session", side_effect=AssertionError("unexpected inference")):
            role = self.create(voice_config=self.voice)
        self.assertEqual(self.fixture.upstream.calls, [])
        self.assertFalse(self.fixture.output.exists())
        self.fixture.manager._process = fixtures.Child()
        result = self.client.post(f'/api/characters/{role["id"]}/synthesize', json={"text": "hello"})
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(self.client.get(result.json()["audio_url"]).content, fixtures.pcm())
        response = self.client.patch("/api/characters/" + role["id"], json={"voice_config": None})
        self.assertIsNone(response.json()["voice_config"])
        self.assertEqual(self.client.post(f'/api/characters/{role["id"]}/synthesize', json={"text": "hello"}).status_code, 409)

    def test_production_binding_dependency_never_constructs_tts_manager(self):
        app.dependency_overrides.pop(get_character_service)
        app.dependency_overrides[get_model_service] = lambda: self.fixture.models
        with patch("api.characters.CHARACTERS_DIR", self.store.directory), \
             patch("api.characters.PROJECT_ROOT", self.fixture.root), \
             patch("api.tts.TTSService", side_effect=AssertionError("unexpected manager creation")):
            role = self.create(voice_config=self.voice)
        self.assertEqual(role["voice_config"]["model_id"], "1234abcd")
        self.assertEqual(self.fixture.upstream.calls, [])

    def test_invalid_fields_and_binding_do_not_save(self):
        role = self.create()
        path = self.store.directory / role["id"] / "config.json"
        original = path.read_bytes()
        for changes, status in (({}, 422), ({"name": None}, 422), ({"id": "x"}, 422),
                                ({"voice_config": self.voice | {"model_id": "missing"}}, 404),
                                ({"voice_config": self.voice | {"reference_audio": "../bad.wav"}}, 422),
                                ({"voice_config": self.voice | {"version": 2}}, 422)):
            response = self.client.patch("/api/characters/" + role["id"], json=changes)
            self.assertEqual(response.status_code, status, response.text)
            self.assertEqual(path.read_bytes(), original)
        response = self.client.post(f'/api/characters/{role["id"]}/synthesize', json={"text": "x", "model_id": "x"})
        self.assertEqual(response.status_code, 422)

    def test_saved_voice_snapshot_survives_concurrent_edit(self):
        role = self.create(voice_config=self.voice)
        self.fixture.upstream.delay = .3
        responses = []
        thread = threading.Thread(target=lambda: responses.append(
            self.client.post(f'/api/characters/{role["id"]}/synthesize', json={"text": "hello"})))
        thread.start()
        try:
            self.assertTrue(self.fixture.upstream.entered.wait(1))
            edited = self.client.patch("/api/characters/" + role["id"],
                json={"voice_config": self.voice | {"prompt_text": "new reference"}})
            self.assertEqual(edited.status_code, 200, edited.text)
        finally: thread.join(3)
        self.assertEqual(responses[0].status_code, 200, responses[0].text)
        body = self.fixture.upstream.calls[2][1]
        self.assertEqual(body["prompt_text"], "reference")
        self.assertEqual(self.store.get(role["id"])["voice_config"]["prompt_text"], "new reference")

    def test_deleted_bound_resources_revalidated_at_synthesis(self):
        role = self.create(voice_config=self.voice)
        (self.fixture.root / "uploads/ref.wav").unlink()
        response = self.client.post(f'/api/characters/{role["id"]}/synthesize', json={"text": "hello"})
        self.assertEqual(response.status_code, 422, response.text)
        self.assertEqual(self.fixture.upstream.calls, [])

    def test_deleted_model_pair_is_not_silently_replaced(self):
        role = self.create(voice_config=self.voice)
        for path in self.fixture.models.gpt_weights_dir.glob("*.ckpt"): path.unlink()
        response = self.client.post(f'/api/characters/{role["id"]}/synthesize', json={"text": "hello"})
        self.assertEqual(response.status_code, 409, response.text)
        for path in self.fixture.models.sovits_weights_dir.glob("*.pth"): path.unlink()
        response = self.client.post(f'/api/characters/{role["id"]}/synthesize', json={"text": "hello"})
        self.assertEqual(response.status_code, 404, response.text)
        self.assertEqual(self.fixture.upstream.calls, [])


if __name__ == "__main__": unittest.main()
