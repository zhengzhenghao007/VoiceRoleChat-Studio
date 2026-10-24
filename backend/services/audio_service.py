"""Validated staged audio assets, metadata fallback and new reference clips."""
import atexit
from datetime import datetime, timezone
import json
import io
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import wave
from threading import RLock
from uuid import uuid4

from anyio import CancelScope
from starlette.concurrency import run_in_threadpool
from schemas.audio import AudioAsset, AudioUploadResponse, DecodedAudio, ReferenceRequest

_storage_lock = RLock()
_worker_lock = RLock()
_failed_workers = []
NAME = re.compile(r"[0-9a-f]{32}\.(wav|mp3|m4a|flac|ogg|webm)")


class AudioError(RuntimeError):
    def __init__(self, message, status_code=422):
        super().__init__(message)
        self.status_code = status_code


def cleanup_failed_workers():
    with _worker_lock:
        for worker in list(_failed_workers):
            try:
                if worker.poll() is None: worker.kill()
                worker.wait(timeout=2)
                if worker.stdout is not None: worker.stdout.close()
                _failed_workers.remove(worker)
            except (OSError, subprocess.TimeoutExpired): pass


atexit.register(cleanup_failed_workers)


def run_audio_worker(path, extension, *, timeout=30, output=None, window=None):
    cleanup_failed_workers()
    if _failed_workers: raise AudioError("A prior audio worker could not be cleaned up; restart the backend",503)
    script = Path(__file__).resolve().parents[1] / "workers/audio_worker.py"
    command = [sys.executable, str(script), "reference" if output else "inspect", "--input", str(path),
               "--extension", extension.lstrip(".")]
    if output:
        command += ["--output",str(output),"--start",str(window.start_seconds),"--end",str(window.end_seconds)]
    process = None
    try:
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, shell=False,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        try:
            raw, _ = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired as error:
            process.kill()
            try: process.communicate(timeout=2)
            except subprocess.TimeoutExpired:
                with _worker_lock: _failed_workers.append(process)
                raise AudioError("Audio worker cleanup failed; ownership retained",503) from error
            raise AudioError("Audio processing deadline exceeded",504) from error
        if process.returncode == 3: raise AudioError("PyAV decoder is unavailable in the backend Python",503)
        if process.returncode == 1: raise AudioError("Audio format, frames, duration or reference window is invalid",422)
        if process.returncode != 0 or not isinstance(raw,bytes) or len(raw) > 65536:
            raise AudioError("Audio worker returned an invalid response",503)
        try: return DecodedAudio.model_validate(json.loads(raw.decode("utf-8")), strict=True).model_dump()
        except (ValueError, TypeError, RecursionError) as error:
            raise AudioError("Audio worker returned invalid metadata",503) from error
    except OSError as error:
        if process is not None and process.poll() is None:
            with _worker_lock: _failed_workers.append(process)
            cleanup_failed_workers()
        raise AudioError("Audio processing worker could not run",503) from error


class AudioService:
    def __init__(self, directory, *, timeout=None, max_size=None, worker=None):
        from config import AUDIO_PROCESS_TIMEOUT, MAX_AUDIO_FILE_SIZE
        self.directory = Path(directory).resolve()
        self.timeout = AUDIO_PROCESS_TIMEOUT if timeout is None else timeout
        self.max_size = MAX_AUDIO_FILE_SIZE if max_size is None else max_size
        self.worker = worker or run_audio_worker

    def audio_path(self, filename):
        if not NAME.fullmatch(filename): raise AudioError("Audio asset not found",404)
        path = self.directory / filename
        try: resolved = path.resolve()
        except (OSError, RuntimeError) as error: raise AudioError("Audio asset path is invalid",404) from error
        if resolved != path or not path.is_file(): raise AudioError("Audio asset not found",404)
        return path

    def _sidecar(self, filename):
        path = self.directory / ".metadata" / (filename + ".json")
        if path.resolve() != path: raise AudioError("Audio metadata directory is invalid",503)
        return path

    def _asset(self, path, metadata=None):
        stat = path.stat()
        result = dict(stored_filename=path.name, original_filename=path.name,
            file_path="uploads/"+path.name, audio_url="/api/voices/"+path.name+"/audio",
            file_size=stat.st_size, created_at=datetime.fromtimestamp(stat.st_mtime,timezone.utc).isoformat(),
            validation_status="uninspected",duration_seconds=None,sample_rate=None,channels=None,codec=None)
        try:
            if metadata is None:
                with self._sidecar(path.name).open("r",encoding="utf-8") as source:
                    text = source.read(65537)
                if len(text) > 65536: raise ValueError("Large metadata")
                metadata = json.loads(text)
            if (not isinstance(metadata,dict) or type(metadata.get("schema_version")) is not int
                    or metadata["schema_version"] != 1 or type(metadata.get("source_size")) is not int
                    or not 0 < metadata["source_size"] <= self.max_size
                    or type(metadata.get("source_mtime_ns")) is not int or metadata.get("source_size") != stat.st_size
                    or metadata.get("source_mtime_ns") != stat.st_mtime_ns): raise ValueError("Stale metadata")
            decoded = DecodedAudio.model_validate(metadata["decoded"],strict=True)
            original = metadata["original_filename"]
            created = metadata["created_at"]
            if (not isinstance(original,str) or not 0 < len(original) <= 255 or not isinstance(created,str)
                    or any(ord(char)<32 for char in original)): raise ValueError("Invalid metadata text")
            result.update(original_filename=original,created_at=created,validation_status="validated",
                duration_seconds=decoded.duration_seconds,sample_rate=decoded.sample_rate,
                channels=decoded.channels,codec=decoded.codec)
        except (OSError,ValueError,TypeError,KeyError,RecursionError,AudioError): pass
        return AudioAsset.model_validate(result).model_dump(mode="json")

    def get(self, filename):
        with _storage_lock: return self._asset(self.audio_path(filename))

    def list(self):
        if not self.directory.exists(): return []
        with _storage_lock:
            result = []
            for path in self.directory.iterdir():
                if not NAME.fullmatch(path.name): continue
                try: result.append(self.get(path.name))
                except AudioError as error:
                    if error.status_code != 404: raise
            return sorted(result,key=lambda item:item["created_at"],reverse=True)

    def _metadata(self,path,original,decoded):
        stat = path.stat()
        return dict(schema_version=1,source_size=stat.st_size,source_mtime_ns=stat.st_mtime_ns,
                    original_filename=original,created_at=datetime.now(timezone.utc).isoformat(),decoded=decoded)

    def _write_metadata(self,path,metadata):
        temporary = None
        try:
            path.parent.mkdir(parents=True,exist_ok=True)
            with tempfile.NamedTemporaryFile("w",encoding="utf-8",dir=path.parent,suffix=".tmp",delete=False) as target:
                temporary=Path(target.name)
                json.dump(metadata,target,ensure_ascii=False,allow_nan=False)
                target.flush(); os.fsync(target.fileno())
            os.replace(temporary,path)
        finally:
            if temporary is not None: temporary.unlink(missing_ok=True)

    def _publish(self,stage,extension,original,decoded):
        try: decoded=DecodedAudio.model_validate(decoded,strict=True).model_dump()
        except (ValueError,TypeError) as error: raise AudioError("Decoded audio metadata is invalid",503) from error
        filename = uuid4().hex + extension
        destination = self.directory / filename
        with _storage_lock:
            if destination.exists(): raise AudioError("Audio filename conflict",409)
            published = False
            try:
                sidecar = self._sidecar(filename)
                metadata = self._metadata(stage,original,decoded)
                os.replace(stage,destination); published = True
                self._write_metadata(sidecar,metadata)
                return AudioUploadResponse(**self._asset(destination,metadata)).model_dump(mode="json")
            except (OSError,ValueError) as error:
                if published: destination.unlink(missing_ok=True)
                raise AudioError("Audio asset could not be published",503) from error

    async def save_upload(self,file):
        stage = writer = None
        try:
            original = file.filename
            if not original: raise AudioError("No filename was provided",400)
            original = original.replace("\\","/").split("/")[-1]
            original = "".join(char for char in original if ord(char)>=32)[:255]
            extension = Path(original).suffix.lower()
            if extension not in {".wav",".mp3",".m4a",".flac",".ogg",".webm"}:
                raise AudioError("Unsupported audio format; use WAV, MP3, M4A, FLAC, OGG or WebM",400)
            await run_in_threadpool(self.directory.mkdir,parents=True,exist_ok=True)
            writer = await run_in_threadpool(tempfile.NamedTemporaryFile,mode="wb",dir=self.directory,suffix=".part",delete=False)
            stage = Path(writer.name)
            size = 0
            while True:
                chunk = await file.read(min(1024*1024,self.max_size-size+1))
                if not chunk: break
                size += len(chunk)
                if size > self.max_size: raise AudioError("Audio exceeds the 50 MiB file limit",413)
                await run_in_threadpool(writer.write,chunk)
            await run_in_threadpool(writer.close); writer=None
            if size == 0: raise AudioError("The uploaded file is empty",400)
            decoded = await run_in_threadpool(self.worker,stage,extension,timeout=self.timeout)
            return await run_in_threadpool(self._publish,stage,extension,original,decoded)
        except OSError as error:
            raise AudioError("Audio upload could not be stored",503) from error
        finally:
            with CancelScope(shield=True):
                if writer is not None: await run_in_threadpool(writer.close)
                if stage is not None: await run_in_threadpool(stage.unlink,missing_ok=True)
                await file.close()

    def inspect(self,filename):
        path = self.audio_path(filename)
        before=path.stat()
        if not 0 < before.st_size <= self.max_size: raise AudioError("Audio exceeds size limits or is empty",413)
        decoded = self.worker(path,path.suffix,timeout=self.timeout)
        with _storage_lock:
            current=self.audio_path(filename).stat()
            if (current.st_size,current.st_mtime_ns) != (before.st_size,before.st_mtime_ns):
                raise AudioError("Audio changed during inspection; retry",409)
            original=self._asset(path)["original_filename"]
            try: self._write_metadata(self._sidecar(filename),self._metadata(path,original,decoded))
            except (OSError,ValueError) as error: raise AudioError("Audio metadata could not be saved",503) from error
            return self.get(filename)

    def create_reference(self,filename,window: ReferenceRequest):
        path=self.audio_path(filename)
        before=path.stat()
        if not 0 < before.st_size <= self.max_size: raise AudioError("Audio exceeds source size limits",413)
        stage=None
        try:
            with tempfile.NamedTemporaryFile(dir=self.directory,suffix=".part",delete=False) as target: stage=Path(target.name)
            decoded=self.worker(path,path.suffix,timeout=self.timeout,output=stage,window=window)
            # Independent output validation reuses the actual binding PCM checker.
            from services.synthesis_service import wav_info, SynthesisError
            if not 0 < stage.stat().st_size <= 10*1024*1024:
                raise AudioError("Reference worker output exceeds size limits",503)
            with stage.open("rb") as audio_file: data=audio_file.read(10*1024*1024+1)
            try:
                rate,duration=wav_info(data)
                with wave.open(io.BytesIO(data)) as audio:
                    expected=round(window.end_seconds*32000)-round(window.start_seconds*32000)
                    if ((audio.getnchannels(),audio.getsampwidth(),rate,audio.getnframes()) != (1,2,32000,expected)
                            or not 3 <= duration <= 10 or decoded.get("sample_rate") != 32000
                            or decoded.get("channels") != 1 or decoded.get("codec") != "pcm_s16le"
                            or decoded.get("source_duration_seconds",0) is None
                            or decoded.get("source_duration_seconds",0) + 1e-9 < window.end_seconds):
                        raise ValueError("Incorrect reference PCM parameters")
            except (SynthesisError,wave.Error,ValueError,TypeError) as error:
                raise AudioError("Reference worker returned invalid normalized PCM audio",503) from error
            current=self.audio_path(filename).stat()
            if (current.st_size,current.st_mtime_ns) != (before.st_size,before.st_mtime_ns):
                raise AudioError("Source changed during reference generation",409)
            result=self._publish(stage,".wav",f"reference-{window.start_seconds:g}-{window.end_seconds:g}.wav",decoded)
            return result | {"reference_audio":result["file_path"]}
        except OSError as error: raise AudioError("Reference audio could not be stored",503) from error
        finally:
            if stage is not None: stage.unlink(missing_ok=True)
