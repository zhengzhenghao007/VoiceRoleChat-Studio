"""Serialized local text synthesis with validated inputs and atomic WAV storage."""
import http.client
import io
import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import socket
import threading
import time
from urllib.parse import urlencode
from uuid import uuid4
import wave

from schemas.tts import SynthesisRequest, SynthesisResult, VoiceSettings
from services.model_service import AmbiguousModelIdError
from services.tts_service import ServiceTimeout, ServiceUnavailable

MAX_AUDIO = 32 * 1024 * 1024
MAX_REFERENCE = 10 * 1024 * 1024


class SynthesisError(ServiceUnavailable):
    def __init__(self, message, status_code=502):
        super().__init__(message)
        self.status_code = status_code


def wav_info(data: bytes):
    try:
        with wave.open(io.BytesIO(data), "rb") as audio:
            channels, width, rate, frames, encoding, _ = audio.getparams()
            if (encoding != "NONE" or channels not in (1, 2) or width not in (1, 2, 3, 4)
                    or not 8000 <= rate <= 192000 or frames <= 0
                    or len(audio.readframes(frames)) != frames * channels * width):
                raise ValueError("Invalid PCM frames")
            return rate, frames / rate
    except (wave.Error, EOFError, ValueError, OSError) as error:
        raise SynthesisError("Audio must be a nonempty complete PCM WAV") from error


def request_upstream(port, method, path, deadline, *, payload=None, limit=65536):
    """One total budget, including slow headers/body; no proxies or redirects."""
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise ServiceTimeout("Synthesis deadline exceeded")
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=remaining)
    timer = None
    try:
        connection.connect()
        sock = connection.sock
        def expire():
            try: sock.shutdown(socket.SHUT_RDWR)
            except OSError: pass
        timer = threading.Timer(max(.001, deadline - time.monotonic()), expire)
        timer.daemon = True
        timer.start()
        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        connection.request(method, path, body=body,
            headers={"Content-Type": "application/json", "Connection": "close"})
        response = connection.getresponse()
        if response.status != 200:
            raise SynthesisError(f"Upstream {path.split('?')[0]} returned HTTP {response.status}")
        data = response.read(limit + 1)
        if time.monotonic() >= deadline:
            raise ServiceTimeout("Synthesis deadline exceeded")
        if len(data) > limit:
            raise SynthesisError("Upstream response exceeds allowed size")
        return data
    except (OSError, http.client.HTTPException) as error:
        if isinstance(error, TimeoutError) or time.monotonic() >= deadline:
            raise ServiceTimeout("Synthesis deadline exceeded") from error
        raise ServiceUnavailable("Inference transport failed; owned service requires restart") from error
    finally:
        if timer: timer.cancel()
        connection.close()


class SynthesisService:
    def __init__(self, manager, models, *, project_root=None, output_root=None):
        from config import PROJECT_ROOT, OUTPUTS_DIR
        self.manager, self.models = manager, models
        self.root = Path(project_root or PROJECT_ROOT).resolve()
        self.output = Path(output_root or OUTPUTS_DIR / "tts").resolve()

    def _reference(self, value):
        path = PurePosixPath(value)
        if ("\\" in value or path.is_absolute() or PureWindowsPath(value).drive
                or ".." in path.parts or not path.parts or path.parts[0] not in {"uploads", "datasets"}):
            raise SynthesisError("Reference must be a relative uploads/ or datasets/ WAV path", 422)
        resolved = (self.root / value).resolve()
        if (not resolved.is_relative_to(self.root / path.parts[0]) or resolved.suffix.lower() != ".wav"):
            raise SynthesisError("Reference path is outside allowed audio directories", 422)
        try:
            with resolved.open("rb") as source:
                data = source.read(MAX_REFERENCE + 1)
        except OSError as error:
            raise SynthesisError("Reference WAV is missing or unreadable", 422) from error
        if len(data) > MAX_REFERENCE:
            raise SynthesisError("Reference exceeds 10 MiB", 422)
        try:
            _, duration = wav_info(data)
        except SynthesisError as error:
            raise SynthesisError(str(error), 422) from error
        if not 3 <= duration <= 10:
            raise SynthesisError("Reference WAV must be between 3 and 10 seconds", 422)
        return data

    def _model(self, identifier):
        try:
            model = self.models.get_model(identifier)
        except AmbiguousModelIdError as error:
            raise SynthesisError(str(error), 409) from error
        if model is None: raise SynthesisError("Model not found", 404)
        if model.status != "ready": raise SynthesisError("Model pair is incomplete", 409)
        paths = []
        for value, suffix, training_root in ((model.gpt, ".ckpt", self.models.gpt_weights_dir),
                                             (model.sovits, ".pth", self.models.sovits_weights_dir)):
            path = Path(value or "")
            path = (path if path.is_absolute() else self.root / path).resolve()
            if (not value or path.suffix.lower() != suffix or not path.is_file()
                    or not any(path.is_relative_to(root.resolve())
                               for root in (training_root, self.root / "models"))):
                raise SynthesisError("Registered model weight is missing or outside allowed directories", 409)
            paths.append(path)
        return model, paths

    def validate_voice(self, settings: VoiceSettings) -> VoiceSettings:
        """Validate a persisted binding without probing or mutating inference."""
        self._reference(settings.reference_audio)
        model, _ = self._model(settings.model_id)
        return settings.model_copy(update={"model_id": model.id})

    def synthesize(self, request: SynthesisRequest) -> SynthesisResult:
        # Snapshot validated reference data before waiting for any upstream work.
        reference = self._reference(request.reference_audio)
        model, weights = self._model(request.model_id)
        identifier = uuid4().hex
        ref_file = self.output / (identifier + ".ref.wav")
        temporary = self.output / (identifier + ".tmp")
        try:
            with self.manager.inference_session() as deadline:
                self.output.mkdir(parents=True, exist_ok=True)
                ref_file.write_bytes(reference)
                for endpoint, weight in zip(("set_gpt_weights", "set_sovits_weights"), weights):
                    raw = request_upstream(self.manager.settings.port, "GET",
                        "/" + endpoint + "?" + urlencode({"weights_path": str(weight)}), deadline)
                    try:
                        ack = json.loads(raw)
                    except (ValueError, RecursionError) as error:
                        raise SynthesisError("Invalid upstream weight acknowledgement") from error
                    if not isinstance(ack, dict) or ack.get("message") != "success":
                        raise SynthesisError("Upstream did not confirm weight selection")
                audio = request_upstream(self.manager.settings.port, "POST", "/tts", deadline,
                    payload={"text": request.text, "text_lang": request.text_lang,
                        "ref_audio_path": str(ref_file), "prompt_text": request.prompt_text,
                        "prompt_lang": request.prompt_lang, "media_type": "wav", "streaming_mode": False,
                        "batch_size": 1, "parallel_infer": False, "seed": 0}, limit=MAX_AUDIO)
                rate, duration = wav_info(audio)
                temporary.write_bytes(audio)
                if time.monotonic() >= deadline:
                    raise ServiceTimeout("Synthesis deadline exceeded")
                os.replace(temporary, self.output / (identifier + ".wav"))
                return SynthesisResult(id=identifier, model_id=model.id,
                    audio_url="/api/tts/audio/" + identifier, sample_rate=rate, duration_seconds=duration)
        except OSError as error:
            raise SynthesisError("Generated audio could not be stored", 503) from error
        finally:
            ref_file.unlink(missing_ok=True)
            temporary.unlink(missing_ok=True)

    def audio_path(self, identifier: str) -> Path:
        if not re.fullmatch(r"[0-9a-f]{32}", identifier):
            raise SynthesisError("Generated audio not found", 404)
        path = (self.output / (identifier + ".wav")).resolve()
        if not path.is_relative_to(self.output) or not path.is_file():
            raise SynthesisError("Generated audio not found", 404)
        return path
