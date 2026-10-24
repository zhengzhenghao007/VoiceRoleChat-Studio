"""Typed synthesis routes backed by the real adapter and fake HTTP upstream."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from fastapi.testclient import TestClient
from app import app
from api.tts import get_synthesis_service
import test_synthesis as fixtures


class SynthesisAPITests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.SynthesisTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        app.dependency_overrides[get_synthesis_service] = lambda: self.fixture.service
        self.addCleanup(app.dependency_overrides.clear)
        self.client = TestClient(app)
        self.addCleanup(self.client.close)

    def test_generate_and_fetch_wav(self):
        result = self.client.post("/api/tts/synthesize", json=self.fixture.payload)
        self.assertEqual(result.status_code, 200, result.text)
        response = self.client.get(result.json()["audio_url"])
        self.assertEqual(response.status_code, 200)
        self.assertIn("audio/wav", response.headers["content-type"])
        self.assertEqual(response.content, fixtures.pcm())

    def test_schema_missing_model_reference_and_output(self):
        for changes, status in (({"text": ""}, 422), ({"text_lang": "xx"}, 422),
                                ({"model_id": "missing"}, 404), ({"reference_audio": "../secret.wav"}, 422)):
            response = self.client.post("/api/tts/synthesize", json=self.fixture.payload | changes)
            self.assertEqual(response.status_code, status, response.text)
        self.assertEqual(self.client.get("/api/tts/audio/" + "0" * 32).status_code, 404)
        self.assertEqual(self.client.get("/api/tts/audio/not-a-uuid").status_code, 404)

    def test_upstream_failure_and_unmanaged_service(self):
        self.fixture.upstream.responses["/tts"] = (200, b'{"error":"failure"}')
        response = self.client.post("/api/tts/synthesize", json=self.fixture.payload)
        self.assertEqual(response.status_code, 502, response.text)
        self.assertFalse(self.fixture.manager.status().managed)
        response = self.client.post("/api/tts/synthesize", json=self.fixture.payload)
        self.assertEqual(response.status_code, 503, response.text)


if __name__ == "__main__": unittest.main()
