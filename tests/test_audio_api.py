"""Audio library API and legacy upload consumers using temporary media only."""
import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import wave

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"backend"))
from fastapi.testclient import TestClient
from app import app
from services.file_service import get_audio_service
from services.audio_service import AudioService, AudioError
import test_audio_library as fixtures


class AudioAPITests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory=Path(self.temp.name)/"uploads"
        self.service=AudioService(self.directory)
        app.dependency_overrides[get_audio_service]=lambda:self.service
        self.addCleanup(app.dependency_overrides.clear)
        self.root_patch=patch("services.file_service.UPLOAD_DIR",self.directory)
        self.root_patch.start();self.addCleanup(self.root_patch.stop)
        self.client=TestClient(app);self.addCleanup(self.client.close)

    def upload(self):
        response=self.client.post("/api/voices/upload",files={"file":("voice.wav",fixtures.wav(),"audio/wav")})
        self.assertEqual(response.status_code,200,response.text)
        return response.json()

    def test_upload_library_detail_audio_and_reference(self):
        result=self.upload()
        listing=self.client.get("/api/voices")
        self.assertEqual(listing.status_code,200,listing.text)
        self.assertEqual(listing.json()["total"],1)
        filename=result["stored_filename"]
        self.assertEqual(self.client.get("/api/voices/"+filename).json()["validation_status"],"validated")
        audio=self.client.get(result["audio_url"])
        self.assertEqual(audio.status_code,200)
        self.assertEqual(audio.headers["x-content-type-options"],"nosniff")
        self.assertEqual(audio.content,fixtures.wav())
        clip=self.client.post(f"/api/voices/{filename}/reference",json={"start_seconds":.5,"end_seconds":3.5})
        self.assertEqual(clip.status_code,200,clip.text)
        with wave.open(io.BytesIO(self.client.get(clip.json()["audio_url"]).content)) as source:
            self.assertEqual((source.getframerate(),source.getnframes()),(32000,96000))
        self.assertEqual(clip.json()["reference_audio"],clip.json()["file_path"])

    def test_invalid_input_paths_and_worker_errors(self):
        response=self.client.post("/api/voices/upload",files={"file":("bad.wav",b"invalid","audio/wav")})
        self.assertEqual(response.status_code,422,response.text)
        self.assertEqual(self.client.get("/api/voices/a.wav/audio").status_code,404)
        self.assertEqual(self.client.get("/api/voices/"+"a"*32+".json/audio").status_code,404)
        result=self.upload()
        for payload in ({"start_seconds":0,"end_seconds":2},{"start_seconds":0,"end_seconds":100}):
            self.assertEqual(self.client.post(f'/api/voices/{result["stored_filename"]}/reference',json=payload).status_code,422)
        with patch.object(self.service,"inspect",side_effect=AudioError("timeout",504)):
            response=self.client.post(f'/api/voices/{result["stored_filename"]}/inspect')
        self.assertEqual(response.status_code,504,response.text)

    def test_legacy_explicit_inspect_never_rewrites_source(self):
        self.directory.mkdir()
        path=self.directory/("b"*32+".wav");path.write_bytes(fixtures.wav())
        before=path.read_bytes(),path.stat().st_mtime_ns
        self.assertEqual(self.client.get("/api/voices").json()["items"][0]["validation_status"],"uninspected")
        response=self.client.post(f"/api/voices/{path.name}/inspect")
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json()["validation_status"],"validated")
        self.assertEqual((path.read_bytes(),path.stat().st_mtime_ns),before)

    def test_upload_and_transcribe_preserves_stored_filename_contract(self):
        def transcript(stored_filename,language=None):
            return dict(stored_filename=stored_filename,language="en",language_probability=1.0,duration=4,
                        text="test",segments=[{"start":0,"end":4,"text":"test"}],transcript_file="transcripts/test.json")
        with patch("api.transcriptions.transcribe_audio",side_effect=transcript) as transcribe:
            response=self.client.post("/api/transcriptions/upload",files={"file":("voice.wav",fixtures.wav(),"audio/wav")})
        self.assertEqual(response.status_code,200,response.text)
        transcribe.assert_called_once()
        self.assertTrue((self.directory/response.json()["stored_filename"]).is_file())


if __name__=="__main__":unittest.main()
