import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from dataclasses import replace
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from services.tts_service import (
    ProbeResult, ServiceConflict, ServiceTimeout, ServiceUnavailable,
    TTSService, TTSSettings, probe_service,
)

SPEC = {"openapi": "3.1.0", "paths": {"/tts": {"post": {}},
        "/set_gpt_weights": {"get": {}}, "/set_sovits_weights": {"get": {}}}}


class FakeHTTP:
    def __init__(self, body=None, code=200, delay=0, trickle=False):
        body = json.dumps(SPEC).encode() if body is None else body
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                try:
                    time.sleep(delay)
                    self.send_response(code)
                    self.send_header("Location", "http://example.invalid/")
                    self.end_headers()
                    if trickle:
                        for char in body:
                            self.wfile.write(bytes([char]))
                            self.wfile.flush()
                            time.sleep(.03)
                    else:
                        self.wfile.write(body)
                except (OSError, ConnectionError):
                    pass
            def log_message(self, *args):
                pass
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
    @property
    def port(self):
        return self.server.server_port
    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(2)


class Process:
    pid = 12345
    def __init__(self, exited=False, stubborn=False, immortal=False):
        self.code = 3 if exited else None
        self.terminated = self.killed = False
        self.stubborn, self.immortal = stubborn, immortal
    def poll(self):
        return self.code
    def terminate(self):
        self.terminated = True
        if not self.stubborn:
            self.code = 0
    def kill(self):
        self.killed = True
        if not self.immortal:
            self.code = -9
    def wait(self, timeout):
        if self.code is None:
            raise subprocess.TimeoutExpired("test-child", timeout)
        return self.code


class TTSServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        tool = root / "tool"
        tool.mkdir()
        (tool / "api_v2.py").touch()
        for name in ("s1.ckpt", "s2.pth"):
            (tool / name).touch()
        (tool / "bert").mkdir()
        (tool / "hubert").mkdir()
        self.yaml = tool / "tts_infer.yaml"
        self.yaml.write_text("original: unchanged", encoding="utf-8")
        self.settings = TTSSettings(tool_root=tool, python=Path(sys.executable),
            s1=tool / "s1.ckpt", s2=tool / "s2.pth", bert=tool / "bert", hubert=tool / "hubert",
            output_root=root / "output", port=9880, request_timeout=.1, start_timeout=.2, stop_timeout=.2)

    def service(self, process=None, ready_after_spawn=True):
        process = process or Process()
        spawned = []
        def factory(*args, **kwargs):
            spawned.append((args, kwargs))
            return process
        def probe(port, timeout):
            return ProbeResult(bool(spawned) and ready_after_spawn, bool(spawned), "fixture")
        manager = TTSService(self.settings, process_factory=factory, probe=probe)
        self.addCleanup(manager.close)
        return manager, process, spawned

    def test_probe_valid_incompatible_and_invalid_responses(self):
        cases = [(None, 200, True), (b"[]", 200, False), (b"{bad", 200, False),
                 (b"[" * 1500 + b"0" + b"]" * 1500, 200, False),
                 (json.dumps({"paths": {"/tts": {"get": {}}}}).encode(), 200, False),
                 (b"x" * (1024 * 1024 + 1), 200, False), (None, 302, False)]
        for body, code, expected in cases:
            with self.subTest(code=code, body_length=len(body or b"")):
                server = FakeHTTP(body, code)
                try:
                    result = probe_service(server.port, .5)
                    self.assertEqual(result.ready, expected)
                    self.assertTrue(result.reachable)
                finally:
                    server.close()

    def test_probe_absent_and_total_deadline(self):
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        self.assertFalse(probe_service(port, .1).reachable)
        for kwargs in ({"delay": .5}, {"trickle": True}):
            server = FakeHTTP(**kwargs)
            try:
                before = time.monotonic()
                self.assertFalse(probe_service(server.port, .15).ready)
                self.assertLess(time.monotonic() - before, .7)
            finally:
                server.close()

    def test_start_private_cpu_config_and_stop_owned(self):
        manager, child, spawned = self.service()
        original = hashlib.sha256(self.yaml.read_bytes()).digest()
        state = manager.start()
        self.assertEqual((state.state, state.managed, state.pid), ("ready", True, child.pid))
        command = spawned[0][0][0]
        self.assertEqual(command[:3], [str(self.settings.python), "-s", "api_v2.py"])
        self.assertIn("127.0.0.1", command)
        config = json.loads(Path(command[-1]).read_text())["custom"]
        self.assertEqual((config["device"], config["is_half"], config["version"]), ("cpu", False, "v2Pro"))
        self.assertEqual(spawned[0][1]["env"]["HF_HUB_OFFLINE"], "1")
        self.assertFalse(spawned[0][1]["shell"])
        self.assertEqual(manager.start().state, "ready")
        self.assertEqual(len(spawned), 1)
        self.assertEqual(manager.stop().state, "stopped")
        self.assertTrue(child.terminated)
        self.assertTrue(spawned[0][1]["stdout"].closed)
        self.assertEqual(hashlib.sha256(self.yaml.read_bytes()).digest(), original)

    def test_unmanaged_service_and_port_conflict_never_spawn_or_stop(self):
        for ready in (True, False):
            factory = Mock()
            manager = TTSService(self.settings, process_factory=factory,
                                 probe=lambda *args, **kwargs: ProbeResult(ready, True, "external"))
            with self.assertRaises(ServiceConflict):
                manager.start()
            with self.assertRaises(ServiceConflict):
                manager.stop()
            manager.close()
            factory.assert_not_called()
            self.assertFalse(manager.status().managed)
            self.assertIsNone(manager.status().pid)

    def test_start_failure_early_exit_and_missing_resources(self):
        manager, _, _ = self.service(Process(exited=True))
        with self.assertRaises(ServiceUnavailable):
            manager.start()
        self.assertEqual(manager.status().state, "failed")
        (self.settings.tool_root / "api_v2.py").unlink()
        other, _, calls = self.service()
        with self.assertRaises(ServiceUnavailable):
            other.start()
        self.assertEqual(calls, [])

    def test_start_timeout_cleanup_and_stop_kill_fallback(self):
        manager, child, _ = self.service(ready_after_spawn=False)
        with self.assertRaises(ServiceTimeout):
            manager.start()
        self.assertTrue(child.terminated)
        self.assertFalse(manager.status().managed)
        other, stubborn, _ = self.service(Process(stubborn=True))
        other.start()
        self.assertEqual(other.stop().state, "stopped")
        self.assertTrue(stubborn.killed)

    def test_cleanup_failure_retains_handle(self):
        child = Process(stubborn=True, immortal=True)
        manager, _, _ = self.service(child)
        manager.start()
        with self.assertRaises(ServiceTimeout):
            manager.stop()
        self.assertTrue(manager.status().managed)
        child.immortal = False
        manager.close()

    def test_concurrent_lifecycle_returns_conflict(self):
        manager, _, _ = self.service()
        entered, release = threading.Event(), threading.Event()
        actual = manager._probe
        def blocked(*args, **kwargs):
            entered.set()
            release.wait(2)
            return actual(*args, **kwargs)
        manager._probe = blocked
        errors = []
        def start():
            try:
                manager.start()
            except Exception as error:
                errors.append(error)
        thread = threading.Thread(target=start)
        thread.start()
        self.assertTrue(entered.wait(1))
        try:
            with self.assertRaises(ServiceConflict):
                manager.stop()
            with self.assertRaises(ServiceConflict):
                manager.start()
        finally:
            release.set()
            thread.join(3)
        self.assertFalse(errors)

    def test_status_during_startup_exit_does_not_discard_owned_handle(self):
        manager, child, calls = self.service()
        def probe(*args):
            if calls:
                child.code = 3
                self.assertEqual(manager.status().state, "starting")
            return ProbeResult(False, bool(calls), "fixture")
        manager._probe = probe
        with self.assertRaises(ServiceUnavailable):
            manager.start()
        self.assertFalse(manager.status().managed)

    def test_real_lightweight_child_and_shutdown(self):
        # This temporary upstream stand-in imports only the Python standard library.
        script = ('import argparse,json\nfrom http.server import BaseHTTPRequestHandler,HTTPServer\n'
                  'p=argparse.ArgumentParser();p.add_argument("-a");p.add_argument("-p",type=int);'
                  'p.add_argument("-c");a=p.parse_args()\n'
                  'assert json.load(open(a.c))["custom"]["device"]=="cpu"\n'
                  'class H(BaseHTTPRequestHandler):\n'
                  ' def do_GET(self):\n'
                  '  self.send_response(200);self.end_headers();self.wfile.write(' + repr(json.dumps(SPEC).encode()) + ')\n'
                  ' def log_message(self,*args): pass\n'
                  'HTTPServer((a.a,a.p),H).serve_forever()\n')
        (self.settings.tool_root / "api_v2.py").write_text(script, encoding="utf-8")
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        settings = replace(self.settings, port=port, request_timeout=.5, start_timeout=5, stop_timeout=2)
        manager = TTSService(settings)
        self.addCleanup(manager.close)
        original = self.yaml.read_bytes()
        state = manager.start()
        child = manager._process
        self.assertTrue(state.managed)
        self.assertEqual(manager.status().state, "ready")
        manager.close()
        self.assertIsNotNone(child.poll())
        self.assertFalse(probe_service(port, .2).ready)
        self.assertEqual(self.yaml.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
