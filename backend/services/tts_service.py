"""Bounded local API probing and lifecycle management of owned children only."""
from dataclasses import dataclass
import http.client
import json
import os
from pathlib import Path
import socket
import subprocess
import threading
import time
from uuid import uuid4

from schemas.tts import ServiceStatus


class ServiceUnavailable(RuntimeError):
    pass


class ServiceConflict(ServiceUnavailable):
    pass


class ServiceTimeout(ServiceUnavailable):
    pass


@dataclass(frozen=True)
class ProbeResult:
    ready: bool
    reachable: bool
    detail: str


def probe_service(port: int, timeout: float) -> ProbeResult:
    """No proxies/redirects; a socket watchdog bounds headers and trickle bodies."""
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
    reachable = False
    timer = None
    deadline = time.monotonic() + timeout
    try:
        connection.connect()
        reachable = True
        sock = connection.sock

        def expire():
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass

        timer = threading.Timer(max(.001, deadline - time.monotonic()), expire)
        timer.daemon = True
        timer.start()
        connection.request("GET", "/openapi.json", headers={"Connection": "close"})
        response = connection.getresponse()
        if response.status != 200:
            return ProbeResult(False, True, f"OpenAPI returned HTTP {response.status}")
        body = response.read(1024 * 1024 + 1)
        if time.monotonic() >= deadline:
            return ProbeResult(False, True, "API probe deadline exceeded")
        if len(body) > 1024 * 1024:
            return ProbeResult(False, True, "OpenAPI response exceeds 1 MiB")
        data = json.loads(body)
        paths = data.get("paths") if isinstance(data, dict) else None
        required = {"/tts": "post", "/set_gpt_weights": "get", "/set_sovits_weights": "get"}
        valid = isinstance(paths, dict) and all(
            isinstance(paths.get(path), dict) and isinstance(paths[path].get(method), dict)
            for path, method in required.items())
        return ProbeResult(bool(valid), True,
            "Compatible GPT-SoVITS API ready; model loadability unverified" if valid else
            "Listener does not expose the required GPT-SoVITS route methods")
    except (OSError, http.client.HTTPException, ValueError, RecursionError) as error:
        return ProbeResult(False, reachable, f"API unavailable ({type(error).__name__})")
    finally:
        if timer is not None:
            timer.cancel()
        connection.close()


@dataclass(frozen=True)
class TTSSettings:
    tool_root: Path
    python: Path
    s1: Path
    s2: Path
    bert: Path
    hubert: Path
    output_root: Path
    port: int = 9880
    request_timeout: float = 2
    start_timeout: float = 120
    stop_timeout: float = 10

    @classmethod
    def from_config(cls):
        import config
        return cls(tool_root=config.GPT_SOVITS_ROOT, python=config.GPT_SOVITS_PYTHON,
            s1=config.GPT_SOVITS_S1_MODEL, s2=config.GPT_SOVITS_S2G_MODEL,
            bert=config.GPT_SOVITS_BERT_DIR, hubert=config.GPT_SOVITS_HUBERT_DIR,
            output_root=config.OUTPUTS_DIR / "tts-service", port=config.GPT_SOVITS_API_PORT,
            request_timeout=config.GPT_SOVITS_REQUEST_TIMEOUT,
            start_timeout=config.GPT_SOVITS_START_TIMEOUT, stop_timeout=config.GPT_SOVITS_STOP_TIMEOUT)


class TTSService:
    def __init__(self, settings=None, *, process_factory=subprocess.Popen,
                 probe=probe_service, clock=time.monotonic, sleep=time.sleep):
        self.settings = settings or TTSSettings.from_config()
        self._factory, self._probe, self._clock, self._sleep = process_factory, probe, clock, sleep
        self._operation = threading.Lock()
        self._guard = threading.RLock()
        self._process = self._log = None
        self._state, self._detail = "unavailable", "Service not started by this backend"

    def _snapshot(self):
        with self._guard:
            return ServiceStatus(state=self._state, managed=self._process is not None,
                pid=self._process.pid if self._process else None, detail=self._detail)

    def _set_state(self, state, detail):
        with self._guard:
            self._state, self._detail = state, detail
        return self._snapshot()

    def _reap(self):
        with self._guard:
            # Startup owns its exit handling and log until the operation completes.
            if self._state == "starting":
                return
            if self._process is not None and self._process.poll() is not None:
                code = self._process.returncode if hasattr(self._process, "returncode") else self._process.poll()
                self._process = None
                if self._log:
                    self._log.close()
                    self._log = None
                self._state, self._detail = "failed", f"Owned process exited ({code}); inspect its runtime log"

    def status(self):
        self._reap()
        state = self._snapshot()
        if state.state in {"starting", "failed"}:
            return state
        result = self._probe(self.settings.port, self.settings.request_timeout)
        if result.ready:
            return ServiceStatus(state="ready", managed=state.managed, pid=state.pid, detail=result.detail)
        if state.state == "stopped" and not result.reachable:
            return state
        return ServiceStatus(state="unavailable", managed=state.managed, pid=state.pid, detail=result.detail)

    def _prepare(self):
        settings = self.settings
        for path in (settings.python, settings.tool_root / "api_v2.py", settings.s1, settings.s2):
            if not path.is_file():
                raise ServiceUnavailable(f"Required local file missing: {path}")
        for path in (settings.tool_root, settings.bert, settings.hubert):
            if not path.is_dir():
                raise ServiceUnavailable(f"Required local directory missing: {path}")
        directory = settings.output_root / uuid4().hex
        directory.mkdir(parents=True, exist_ok=False)
        private_config = directory / "config.json"
        private_config.write_text(json.dumps({"custom": {
            "device": "cpu", "is_half": False, "version": "v2Pro",
            "t2s_weights_path": str(settings.s1.resolve()), "vits_weights_path": str(settings.s2.resolve()),
            "bert_base_path": str(settings.bert.resolve()), "cnhuhbert_base_path": str(settings.hubert.resolve()),
        }}, indent=2), encoding="utf-8")
        return private_config, directory / "service.log"

    def _cleanup(self):
        with self._guard:
            process = self._process
        if process is not None and process.poll() is None:
            try:
                process.terminate()
                try:
                    process.wait(timeout=self.settings.stop_timeout / 2)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=self.settings.stop_timeout / 2)
            except (OSError, subprocess.TimeoutExpired) as error:
                if process.poll() is None:
                    self._set_state("failed", "Owned process cleanup failed; ownership retained for retry")
                    raise ServiceTimeout(self._detail) from error
        with self._guard:
            self._process = None
            if self._log:
                self._log.close()
                self._log = None

    def start(self):
        if not self._operation.acquire(blocking=False):
            raise ServiceConflict("Another service lifecycle operation is in progress")
        try:
            self._reap()
            if self._process is not None:
                state = self.status()
                if state.state == "ready":
                    return state
                raise ServiceConflict("Owned service exists; stop it before retrying startup")
            existing = self._probe(self.settings.port, self.settings.request_timeout)
            if existing.reachable:
                raise ServiceConflict("Port already occupied; existing listener will not be adopted")
            self._set_state("starting", "Starting owned CPU GPT-SoVITS service")
            try:
                private_config, log = self._prepare()
                environment = os.environ.copy()
                environment.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", HF_DATASETS_OFFLINE="1")
                prefix = self.settings.python.parent
                environment["PATH"] = os.pathsep.join([str(prefix / "Library/bin"), str(prefix / "DLLs"),
                                                       environment.get("PATH", "")])
                with self._guard:
                    self._log = log.open("ab")
                    self._process = self._factory([str(self.settings.python), "-s", "api_v2.py",
                        "-a", "127.0.0.1", "-p", str(self.settings.port), "-c", str(private_config)],
                        cwd=str(self.settings.tool_root), env=environment, shell=False,
                        stdout=self._log, stderr=subprocess.STDOUT,
                        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
                deadline = self._clock() + self.settings.start_timeout
                while True:
                    if self._process.poll() is not None:
                        raise ServiceUnavailable("Owned process exited during startup; inspect " + str(log))
                    remaining = deadline - self._clock()
                    if remaining <= 0:
                        raise ServiceTimeout("Service startup deadline exceeded; inspect " + str(log))
                    result = self._probe(self.settings.port, min(self.settings.request_timeout, remaining))
                    if result.ready and self._process.poll() is None:
                        return self._set_state("ready", result.detail)
                    self._sleep(min(.1, max(0, deadline - self._clock())))
            except (OSError, ServiceUnavailable) as error:
                self._cleanup()
                self._set_state("failed", str(error))
                if isinstance(error, ServiceUnavailable):
                    raise
                raise ServiceUnavailable(f"Service could not start ({type(error).__name__})") from error
        finally:
            self._operation.release()

    def stop(self):
        if not self._operation.acquire(blocking=False):
            raise ServiceConflict("Another service lifecycle operation is in progress")
        try:
            self._reap()
            if self._process is None:
                if self._probe(self.settings.port, self.settings.request_timeout).reachable:
                    raise ServiceConflict("Listener is not owned by this backend; it will not be stopped")
            self._cleanup()
            return self._set_state("stopped", "Owned service stopped; no external process was terminated")
        finally:
            self._operation.release()

    def close(self):
        limit = self.settings.start_timeout + self.settings.request_timeout + 2 * self.settings.stop_timeout
        if not self._operation.acquire(timeout=limit):
            raise ServiceTimeout("Shutdown could not acquire lifecycle operation lock")
        try:
            self._cleanup()
        finally:
            self._operation.release()
