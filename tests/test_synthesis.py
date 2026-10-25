"""Isolated HTTP synthesis and safe artifact transaction tests, no ML models."""
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
from pathlib import Path
import sys
import subprocess
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import wave

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from pydantic import ValidationError
from schemas.tts import SynthesisRequest
from services.model_service import ModelService, AmbiguousModelIdError
from services.synthesis_service import SynthesisService, SynthesisError
from services.tts_service import TTSService, TTSSettings, ProbeResult, ServiceConflict, ServiceTimeout, ServiceUnavailable


def pcm(seconds=.25, rate=16000):
    stream = io.BytesIO()
    with wave.open(stream, "wb") as audio:
        audio.setparams((1, 2, rate, 0, "NONE", "not compressed"))
        audio.writeframes(b"\0\0" * int(seconds * rate))
    return stream.getvalue()


class Child:
    pid = 123
    code = None
    def poll(self): return self.code
    def terminate(self): self.code = 0
    def kill(self): self.code = -9
    def wait(self, timeout): return self.code


class Upstream:
    def __init__(self):
        self.calls = []
        self.responses = {}
        self.delay = 0
        self.trickle = False
        self.entered, self.release = threading.Event(), threading.Event()
        owner = self
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self): self.reply()
            def do_POST(self): self.reply()
            def reply(self):
                try:
                    body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
                    owner.calls.append((self.path, json.loads(body) if body else None))
                    route = self.path.split("?")[0]
                    if route == "/tts":
                        owner.entered.set()
                        if owner.delay: time.sleep(owner.delay)
                    response = owner.responses.get(route,
                        (200, pcm()) if route == "/tts" else (200, b'{"message":"success"}'))
                    if response is None:
                        self.close_connection = True
                        return
                    status, data = response
                    self.send_response(status)
                    self.end_headers()
                    if owner.trickle and route == "/tts":
                        for byte in data:
                            self.wfile.write(bytes([byte])); self.wfile.flush(); time.sleep(.02)
                    else:
                        self.wfile.write(data)
                except (OSError, ConnectionError): pass
            def log_message(self, *args): pass
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=lambda: self.server.serve_forever(poll_interval=.02), daemon=True)
        self.thread.start()
    def close(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join(2)


class SynthesisTests(unittest.TestCase):
    def test_watchdog_abort_is_timeout_even_if_platform_timer_wakes_early(self):
        from services.synthesis_service import request_upstream
        class ImmediateTimer:
            def __init__(self,delay,callback):self.callback=callback
            def start(self):self.callback()
            def cancel(self):pass
        class Socket:
            def shutdown(self,how):pass
        class Connection:
            sock=Socket()
            def connect(self):pass
            def request(self,*args,**kwargs):pass
            def getresponse(self):raise ConnectionAbortedError('watchdog shutdown')
            def close(self):pass
        with patch('services.synthesis_service.threading.Timer',ImmediateTimer),patch('services.synthesis_service.http.client.HTTPConnection',return_value=Connection()):
            with self.assertRaises(ServiceTimeout):request_upstream(1,'POST','/tts',time.monotonic()+10)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        tool = self.root / "tool"
        for folder, name in (("GPT_weights_v2Pro", "actor_1234abcd-e1.ckpt"),
                             ("SoVITS_weights_v2Pro", "actor_1234abcd_e1_s1.pth")):
            (tool / folder).mkdir(parents=True)
            (tool / folder / name).touch()
        (self.root / "uploads").mkdir()
        (self.root / "uploads/ref.wav").write_bytes(pcm(3))
        self.models = ModelService(self.root, tool / "GPT_weights_v2Pro", tool / "SoVITS_weights_v2Pro")
        self.upstream = Upstream()
        self.addCleanup(self.upstream.close)
        settings = TTSSettings(tool, Path(sys.executable), tool / "gpt", tool / "sovits",
                               tool / "bert", tool / "hubert", self.root / "runtime",
                               port=self.upstream.server.server_port, request_timeout=.2,
                               stop_timeout=.2, synthesis_timeout=2)
        self.manager = TTSService(settings, probe=lambda *args: ProbeResult(True, True, "fixture"))
        self.child = Child()
        self.manager._process = self.child
        self.manager._state = "ready"
        self.addCleanup(self.manager.close)
        self.output = self.root / "outputs/tts"
        self.service = SynthesisService(self.manager, self.models, project_root=self.root, output_root=self.output)
        self.payload = dict(model_id="1234abcd", text="test", text_lang="en", prompt_lang="en",
                            reference_audio="uploads/ref.wav", prompt_text="reference")
    def request(self, **kwargs):
        return SynthesisRequest(**(self.payload | kwargs))

    def test_success_order_reselect_and_generated_file(self):
        first = self.service.synthesize(self.request())
        second = self.service.synthesize(self.request())
        self.assertEqual([p.split("?")[0] for p, _ in self.upstream.calls],
                         ["/set_gpt_weights", "/set_sovits_weights", "/tts"] * 2)
        self.assertNotEqual(first.id, second.id)
        self.assertEqual(first.sample_rate, 16000)
        self.assertEqual(first.duration_seconds, .25)
        self.assertEqual(self.service.audio_path(first.id).read_bytes(), pcm())
        body = self.upstream.calls[2][1]
        self.assertEqual((body["media_type"], body["streaming_mode"]), ("wav", False))
        self.assertTrue(Path(body["ref_audio_path"]).is_absolute())
        self.assertEqual(len(list(self.output.glob("*.wav"))), 2)

    def test_request_schema_rejects_empty_long_or_unsupported(self):
        for changes in ({"text": " "}, {"text": "x" * 1001}, {"prompt_text": ""},
                        {"text_lang": "fr"}, {"model_id": ""}, {"reference_audio": "uploads/bad\0.wav"}):
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                self.request(**changes)

    def test_reference_paths_formats_and_complete_frames(self):
        (self.root / "uploads/bad.wav").write_bytes(pcm(3)[:-4])
        (self.root / "uploads/short.wav").write_bytes(pcm(.1))
        (self.root / "uploads/long.wav").write_bytes(pcm(10.1))
        (self.root / "uploads/no.wav").write_bytes(b"not a wave")
        for path in ("../ref.wav", str(self.root / "uploads/ref.wav"), "uploads/../uploads/ref.wav",
                     "uploads/bad.wav", "uploads/short.wav", "uploads/long.wav", "uploads/no.wav",
                     "uploads/missing.wav", "uploads/ref.mp3", "C:/outside.wav"):
            with self.subTest(path=path), self.assertRaises(SynthesisError):
                self.service.synthesize(self.request(reference_audio=path))
        self.assertEqual(self.upstream.calls, [])
        self.assertIsNone(self.child.poll())

    def test_registry_errors_and_weight_path_escape(self):
        with self.assertRaises(SynthesisError) as error:
            self.service.synthesize(self.request(model_id="missing"))
        self.assertEqual(error.exception.status_code, 404)
        model = self.models.get_model("1234abcd")
        (self.root / "outside.ckpt").touch()
        for changes in ({"status": "incomplete"}, {"gpt": str(self.root / "outside.ckpt")}):
            with patch.object(self.models, "get_model", return_value=model.model_copy(update=changes)):
                with self.assertRaises(SynthesisError): self.service.synthesize(self.request())
        with patch.object(self.models, "get_model", side_effect=AmbiguousModelIdError("ambiguous")):
            with self.assertRaises(SynthesisError) as error: self.service.synthesize(self.request())
            self.assertEqual(error.exception.status_code, 409)
        self.assertEqual(self.upstream.calls, [])

    def test_unmanaged_service_never_mutated(self):
        self.manager._process = None
        with self.assertRaises(ServiceUnavailable): self.service.synthesize(self.request())
        self.assertEqual(self.upstream.calls, [])

    def test_partial_weight_failure_and_invalid_ack_cleanup(self):
        for ack in (b'{"message":"failed"}', b'[]', b'invalid'):
            self.manager._process = Child(); self.manager._state = "ready"
            self.upstream.responses["/set_sovits_weights"] = (200, ack)
            with self.assertRaises(SynthesisError): self.service.synthesize(self.request())
            self.assertFalse(self.manager.status().managed)
        self.assertNotIn("/tts", [p for p, _ in self.upstream.calls])

    def test_invalid_empty_truncated_and_large_audio_cleanup(self):
        for audio in (b'{}', pcm(0), pcm()[:-4], b"x" * (32 * 1024 * 1024 + 1)):
            self.manager._process = Child(); self.manager._state = "ready"
            self.upstream.responses["/tts"] = (200, audio)
            with self.assertRaises(SynthesisError): self.service.synthesize(self.request())
            self.assertFalse(self.manager.status().managed)
            self.assertFalse(list(self.output.glob("*.wav")))

    def test_deadline_covers_slow_headers_and_trickle(self):
        self.manager.settings = replace(self.manager.settings, synthesis_timeout=.15)
        for delay, trickle in ((.4, False), (0, True)):
            self.manager._process = Child(); self.manager._state = "ready"
            self.upstream.delay, self.upstream.trickle = delay, trickle
            before = time.monotonic()
            with self.assertRaises(ServiceTimeout): self.service.synthesize(self.request())
            self.assertLess(time.monotonic() - before, .8)
            self.assertFalse(self.manager.status().managed)

    def test_concurrent_synthesis_and_stop_conflict(self):
        self.upstream.delay = .4
        errors = []
        def synthesize():
            try: self.service.synthesize(self.request())
            except Exception as error: errors.append(error)
        thread = threading.Thread(target=synthesize)
        thread.start()
        try:
            self.assertTrue(self.upstream.entered.wait(1))
            with self.assertRaises(ServiceConflict): self.service.synthesize(self.request())
            with self.assertRaises(ServiceConflict): self.manager.stop()
        finally: thread.join(3)
        self.assertEqual(errors, [])

    def test_output_failure_and_retrieval_escape(self):
        with patch("services.synthesis_service.os.replace", side_effect=OSError("disk full")):
            with self.assertRaises(SynthesisError): self.service.synthesize(self.request())
        self.assertEqual(list(self.output.iterdir()), [])
        for identifier in ("../ref", "x", "0" * 32):
            with self.assertRaises(SynthesisError): self.service.audio_path(identifier)

    def test_reference_size_and_resolved_escape(self):
        (self.root / "uploads/large.wav").write_bytes(b"x" * (10 * 1024 * 1024 + 1))
        with self.assertRaises(SynthesisError):
            self.service.synthesize(self.request(reference_audio="uploads/large.wav"))
        outside = self.root / "outside.wav"
        outside.write_bytes(pcm(3))
        resolve = Path.resolve
        def escaped(path, *args, **kwargs):
            return outside if path == self.root / "uploads/link.wav" else resolve(path, *args, **kwargs)
        with patch.object(Path, "resolve", autospec=True, side_effect=escaped):
            with self.assertRaises(SynthesisError):
                self.service.synthesize(self.request(reference_audio="uploads/link.wav"))
        with patch.object(Path, "resolve", return_value=outside):
            with self.assertRaises(SynthesisError): self.service.audio_path("a" * 32)
        self.assertEqual(self.upstream.calls, [])

    def test_disconnect_and_redirect_cleanup(self):
        for response, exception in ((None, ServiceUnavailable), ((302, b""), SynthesisError),
                                    ((400, b'{"message":"failed"}'), SynthesisError)):
            self.manager._process = Child(); self.manager._state = "ready"
            self.upstream.responses["/set_gpt_weights"] = response
            with self.assertRaises(exception): self.service.synthesize(self.request())
            self.assertFalse(self.manager.status().managed)

    def test_uncertain_failure_retains_live_handle_and_blocks_retry(self):
        class Immortal(Child):
            def terminate(self): pass
            def kill(self): pass
            def wait(self, timeout): raise subprocess.TimeoutExpired("fixture", timeout)
        child = Immortal()
        self.manager._process = child
        self.upstream.responses["/tts"] = None
        with self.assertRaises(ServiceTimeout): self.service.synthesize(self.request())
        self.assertEqual((self.manager.status().state, self.manager.status().managed), ("failed", True))
        before = len(self.upstream.calls)
        try:
            with self.assertRaises(ServiceUnavailable): self.service.synthesize(self.request())
            self.assertEqual(len(self.upstream.calls), before)
        finally:
            child.code = 0

    def test_status_reaps_child_during_readiness_probe(self):
        def probe(*args):
            self.child.code = 3
            self.manager.status()
            return ProbeResult(True, True, "fixture")
        self.manager._probe = probe
        with self.assertRaises(ServiceUnavailable): self.service.synthesize(self.request())
        self.assertEqual(self.upstream.calls, [])


if __name__ == "__main__": unittest.main()
