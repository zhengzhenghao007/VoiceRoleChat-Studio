"""Actual bounded audio decode/storage tests in temporary directories."""
import asyncio
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
import wave

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from pydantic import ValidationError
from schemas.audio import ReferenceRequest
from services.audio_service import AudioService, AudioError, run_audio_worker
from services.file_service import save_uploaded_audio


def wav(seconds=4, rate=16000):
    output = io.BytesIO()
    with wave.open(output, "wb") as audio:
        audio.setparams((1,2,rate,0,"NONE","not compressed"))
        audio.writeframes(b"\0\1" * int(seconds * rate))
    return output.getvalue()


class Upload:
    def __init__(self, data, name="sample.wav"):
        self.data = io.BytesIO(data)
        self.filename, self.closed, self.read_sizes = name, False, []
    async def read(self, size):
        self.read_sizes.append(size)
        assert 0 < size <= 1024 * 1024, "Upload read must be bounded"
        return self.data.read(size)
    async def close(self): self.closed = True; self.data.close()


class AudioLibraryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name) / "uploads"
        self.service = AudioService(self.directory)
    def upload(self, data=None, name="sample.wav", service=None):
        upload = Upload(wav() if data is None else data, name)
        result = asyncio.run((service or self.service).save_upload(upload))
        self.assertTrue(upload.closed)
        self.assertTrue(upload.read_sizes)
        return result

    def test_upload_actual_decode_metadata_and_helper_contract(self):
        result = self.upload()
        for key in ("message", "original_filename", "stored_filename", "file_size", "file_path"):
            self.assertIn(key, result)
        self.assertEqual((result["validation_status"], result["duration_seconds"], result["sample_rate"], result["channels"]),
                         ("validated", 4, 16000, 1))
        self.assertEqual(self.service.audio_path(result["stored_filename"]).read_bytes(), wav())
        self.assertEqual(self.service.list()[0]["stored_filename"], result["stored_filename"])
        with patch("services.file_service.UPLOAD_DIR", self.directory):
            helper = asyncio.run(save_uploaded_audio(Upload(wav(), "helper.wav")))
        self.assertEqual(helper["file_path"], "uploads/" + helper["stored_filename"])

    def test_invalid_empty_unsupported_mismatched_and_truncated_never_publish(self):
        cases = [(b"", "empty.wav", 400), (b"not audio", "bad.wav", 422),
                 (wav()[:-4], "truncated.wav", 422), (wav(), "pretend.mp3", 422),
                 (b"script", "script.exe", 400)]
        for data, filename, status in cases:
            upload = Upload(data, filename)
            with self.subTest(filename=filename), self.assertRaises(AudioError) as error:
                asyncio.run(self.service.save_upload(upload))
            self.assertEqual(error.exception.status_code, status)
            self.assertTrue(upload.closed)
            self.assertEqual(self.service.list(), [])
            self.assertEqual(list(self.directory.glob("*.part")), [])

    def test_size_checked_during_bounded_reads(self):
        service = AudioService(self.directory, max_size=65536)
        source = Upload(b"x" * 100000)
        with self.assertRaises(AudioError) as error: asyncio.run(service.save_upload(source))
        self.assertEqual(error.exception.status_code, 413)
        self.assertTrue(source.closed)
        self.assertLessEqual(max(source.read_sizes), 65537)
        self.assertEqual(service.list(), [])

    def test_worker_error_timeout_missing_decoder_and_protocol(self):
        for exception in (AudioError("timeout",504), AudioError("decoder missing",503)):
            service = AudioService(self.directory, worker=Mock(side_effect=exception))
            with self.assertRaises(AudioError) as error: self.upload(service=service)
            self.assertEqual(error.exception.status_code, exception.status_code)
            self.assertEqual(service.list(), [])
        process = Mock(returncode=-9)
        process.communicate.side_effect = [subprocess.TimeoutExpired("worker", .1), (b"",None)]
        with patch("services.audio_service.subprocess.Popen", return_value=process):
            with self.assertRaises(AudioError) as error:
                run_audio_worker(self.directory / "x.part", ".wav", timeout=.1)
            self.assertEqual(error.exception.status_code, 504)
            process.kill.assert_called_once()
        for status, output in ((3,b'{"error":"missing"}'), (0,b'[]'), (0,b'invalid'), (0,b'x'*65537)):
            process = Mock(returncode=status)
            process.communicate.return_value = (output,None)
            with patch("services.audio_service.subprocess.Popen", return_value=process):
                with self.assertRaises(AudioError): run_audio_worker(self.directory / "x.part", ".wav")

    def test_legacy_list_is_read_only_then_explicit_inspect(self):
        self.directory.mkdir()
        path = self.directory / ("a" * 32 + ".wav")
        path.write_bytes(wav())
        original, stamp = path.read_bytes(), path.stat().st_mtime_ns
        asset = self.service.list()[0]
        self.assertEqual(asset["validation_status"], "uninspected")
        self.assertIsNone(asset["duration_seconds"])
        self.assertEqual(list(self.directory.iterdir()), [path])
        inspected = self.service.inspect(path.name)
        self.assertEqual(inspected["validation_status"], "validated")
        self.assertEqual((path.read_bytes(), path.stat().st_mtime_ns), (original,stamp))

    def test_bad_stale_and_future_metadata_falls_back_without_hiding_audio(self):
        result = self.upload()
        path = self.service.audio_path(result["stored_filename"])
        sidecar = self.directory / ".metadata" / (path.name + ".json")
        original = json.loads(sidecar.read_text())
        for raw in (b'{bad', b'[]', json.dumps(original | {"schema_version":99}).encode(),
                    json.dumps(original | {"source_size":0}).encode()):
            sidecar.write_bytes(raw)
            asset = self.service.get(path.name)
            self.assertEqual(asset["validation_status"], "uninspected")
            self.assertIsNone(asset["duration_seconds"])
            self.assertEqual(len(self.service.list()), 1)

    def test_reference_is_new_exact_pcm_and_original_unchanged(self):
        result = self.upload(wav(6,44100))
        path = self.service.audio_path(result["stored_filename"])
        original, stamp = path.read_bytes(), path.stat().st_mtime_ns
        clipped = self.service.create_reference(path.name, ReferenceRequest(start_seconds=.5,end_seconds=3.5))
        self.assertNotEqual(clipped["stored_filename"], path.name)
        self.assertEqual(clipped["reference_audio"], clipped["file_path"])
        with wave.open(str(self.service.audio_path(clipped["stored_filename"]))) as audio:
            self.assertEqual((audio.getnchannels(), audio.getsampwidth(), audio.getframerate(), audio.getnframes()), (1,2,32000,96000))
        self.assertEqual((path.read_bytes(), path.stat().st_mtime_ns), (original,stamp))
        self.assertEqual(len(self.service.list()),2)

    def test_reference_windows_and_missing_samples(self):
        for values in ({"start_seconds":-1,"end_seconds":3}, {"start_seconds":0,"end_seconds":2.9},
                       {"start_seconds":0,"end_seconds":10.1}, {"start_seconds":float("nan"),"end_seconds":4},
                       {"start_seconds":0,"end_seconds":float("inf")}):
            with self.assertRaises(ValidationError): ReferenceRequest(**values)
        result = self.upload()
        with self.assertRaises(AudioError) as error:
            self.service.create_reference(result["stored_filename"], ReferenceRequest(start_seconds=2,end_seconds=5))
        self.assertEqual(error.exception.status_code,422)
        self.assertEqual(len(self.service.list()),1)

    def test_canonical_paths_and_resolved_escape(self):
        result = self.upload()
        for value in ("../x.wav", "a.wav", "A"*32+".wav", "0"*32+".json", "0"*32+".wav"):
            with self.assertRaises(AudioError) as error: self.service.audio_path(value)
            self.assertEqual(error.exception.status_code,404)
        with patch.object(Path,"resolve",return_value=Path(self.temp.name)/"outside.wav"):
            with self.assertRaises(AudioError): self.service.audio_path(result["stored_filename"])

    def test_publication_failure_rolls_back_only_new_asset(self):
        existing = self.upload()
        source = self.service.audio_path(existing["stored_filename"])
        original = source.read_bytes()
        replace = __import__("os").replace
        def fail_metadata(first, second):
            if str(second).endswith(".json"): raise OSError("disk")
            return replace(first,second)
        with patch("services.audio_service.os.replace",side_effect=fail_metadata):
            with self.assertRaises(AudioError): self.upload()
            with self.assertRaises(AudioError):
                self.service.create_reference(source.name,ReferenceRequest(start_seconds=0,end_seconds=3))
        self.assertEqual(source.read_bytes(),original)
        self.assertEqual(len(self.service.list()),1)
        self.assertEqual(list(self.directory.rglob("*.part")),[])
        self.assertEqual(list(self.directory.rglob("*.tmp")),[])

    def test_reference_worker_output_is_independently_normalized_and_bounded(self):
        existing=self.upload()
        def wrong_output(path,extension,*,timeout,output,window):
            output.write_bytes(wav(3,16000))
            return dict(duration_seconds=3.0,sample_rate=32000,channels=1,codec="pcm_s16le",
                        processed_samples=96000,frame_count=3,source_duration_seconds=4.0)
        service=AudioService(self.directory,worker=wrong_output)
        with self.assertRaises(AudioError) as error:
            service.create_reference(existing["stored_filename"],ReferenceRequest(start_seconds=0,end_seconds=3))
        self.assertEqual(error.exception.status_code,503)
        self.assertEqual(len(self.service.list()),1)

    def test_decoder_budget_and_sample_rate_rejection(self):
        with self.assertRaises(AudioError): self.upload(wav(4,4000))
        import av
        from workers.audio_worker import process
        from argparse import Namespace
        self.directory.mkdir(exist_ok=True)
        source=self.directory/"budget.wav";source.write_bytes(wav())
        arguments=Namespace(input=str(source),extension="wav",action="inspect",output=None,start=0,end=None)
        with patch("workers.audio_worker.MAX_SAMPLES",100):
            with self.assertRaises(ValueError): process(arguments,av)

    def test_real_mp3_decode_and_reference_conversion(self):
        import av
        import numpy as np
        from fractions import Fraction
        encoded=Path(self.temp.name)/"source.mp3"
        with av.open(str(encoded),"w",format="mp3") as output:
            stream=output.add_stream("libmp3lame",rate=16000)
            stream.layout="mono"
            frame=av.AudioFrame.from_ndarray(np.full((1,64000),256,dtype=np.int16),format="s16",layout="mono")
            frame.sample_rate=16000;frame.pts=0;frame.time_base=Fraction(1,16000)
            for packet in stream.encode(frame): output.mux(packet)
            for packet in stream.encode(None): output.mux(packet)
        result=self.upload(encoded.read_bytes(),"source.mp3")
        self.assertTrue(result["codec"].startswith("mp3"))
        self.assertAlmostEqual(result["duration_seconds"],4,places=1)
        clipped=self.service.create_reference(result["stored_filename"],ReferenceRequest(start_seconds=.25,end_seconds=3.25))
        self.assertEqual((clipped["sample_rate"],clipped["channels"],clipped["duration_seconds"]),(32000,1,3))


if __name__ == "__main__": unittest.main()
