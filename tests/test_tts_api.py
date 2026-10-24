"""Service API contracts and normal shutdown without loading ML models."""
from pathlib import Path
import sys
import unittest
from concurrent.futures import ThreadPoolExecutor
import threading
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from fastapi.testclient import TestClient
from app import app
from api.tts import get_tts_service, _cached_service
from schemas.tts import ServiceStatus
from services.tts_service import ServiceConflict, ServiceTimeout, ServiceUnavailable


class TTSAPITests(unittest.TestCase):
    def tearDown(self):
        app.dependency_overrides.clear()
        _cached_service.cache_clear()

    def test_routes_and_typed_responses(self):
        manager = Mock()
        manager.status.return_value = ServiceStatus(state="unavailable", detail="absent")
        manager.start.return_value = ServiceStatus(state="ready", managed=True, pid=12, detail="fixture")
        manager.stop.return_value = ServiceStatus(state="stopped", detail="done")
        app.dependency_overrides[get_tts_service] = lambda: manager
        with TestClient(app) as client:
            self.assertEqual(client.get("/health").json(), {"status": "healthy"})
            self.assertEqual(client.get("/api/tts/service").json()["state"], "unavailable")
            result = client.post("/api/tts/service/start")
            self.assertEqual(result.status_code, 200)
            self.assertEqual((result.json()["managed"], result.json()["pid"]), (True, 12))
            self.assertEqual(client.post("/api/tts/service/stop").json()["state"], "stopped")
            paths = client.get("/openapi.json").json()["paths"]
            self.assertIn("get", paths["/api/tts/service"])
            self.assertIn("post", paths["/api/tts/service/start"])
        manager.close.assert_not_called()  # Overrides are owned by this test, not the singleton.

    def test_error_mapping(self):
        manager = Mock()
        app.dependency_overrides[get_tts_service] = lambda: manager
        with TestClient(app) as client:
            for exception, code in ((ServiceConflict, 409), (ServiceTimeout, 504), (ServiceUnavailable, 503)):
                for operation in ("start", "stop"):
                    with self.subTest(exception=exception, operation=operation):
                        getattr(manager, operation).side_effect = exception("fixture error")
                        response = client.post("/api/tts/service/" + operation)
                        self.assertEqual(response.status_code, code)
                        self.assertEqual(response.json(), {"detail": "fixture error"})

    def test_no_startup_creation_and_cached_shutdown(self):
        with patch("api.tts.TTSService") as factory:
            with TestClient(app):
                factory.assert_not_called()
            with TestClient(app) as client:
                factory.return_value.status.return_value = ServiceStatus(state="unavailable", detail="absent")
                client.get("/api/tts/service")
                client.get("/api/tts/service")
                factory.assert_called_once_with()
                factory.return_value.start.assert_not_called()
            factory.return_value.close.assert_called_once_with()
            self.assertEqual(_cached_service.cache_info().currsize, 0)

    def test_concurrent_first_requests_share_one_manager(self):
        entered, release = threading.Event(), threading.Event()
        def construct():
            entered.set()
            release.wait(2)
            return Mock()
        with patch("api.tts.TTSService", side_effect=construct) as factory:
            with ThreadPoolExecutor(2) as executor:
                first = executor.submit(get_tts_service)
                self.assertTrue(entered.wait(1))
                second = executor.submit(get_tts_service)
                # Both callers must receive the same process ownership manager.
                release.set()
                self.assertIs(first.result(3), second.result(3))
            factory.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
