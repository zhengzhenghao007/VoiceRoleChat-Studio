"""Same-origin static workbench keeps existing API entry points intact."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from fastapi.testclient import TestClient
from app import app


class StudioStaticTests(unittest.TestCase):
    def test_workbench_and_assets(self):
        with TestClient(app) as client:
            response = client.get("/studio/")
            self.assertEqual(response.status_code, 200)
            self.assertIn('lang="zh-CN"', response.text)
            for asset in ("app.js", "audio.js", "transcriptions.js", "datasets.js", "style.css"):
                self.assertEqual(client.get("/studio/" + asset).status_code, 200)
            self.assertEqual(client.get("/").json(), {"message": "VoiceRoleChat Studio backend is running"})
            self.assertEqual(client.get("/health").json(), {"status": "healthy"})


if __name__ == "__main__": unittest.main()
