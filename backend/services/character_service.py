"""Single-process, version-aware and atomic character JSON storage."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import tempfile
from threading import RLock
from uuid import uuid4

from pydantic import ValidationError
from schemas.character import CharacterCreate, CharacterPatch, CharacterResponse, VoiceConfiguration

_write_lock = RLock()


class CharacterError(RuntimeError):
    def __init__(self, message, status_code=500):
        super().__init__(message)
        self.status_code = status_code


class CharacterService:
    def __init__(self, directory: Path, *, voice_validator=None):
        self.directory = Path(directory).resolve()
        self.voice_validator = voice_validator

    def _path(self, identifier):
        if not re.fullmatch(r"[0-9a-f]{32}", identifier):
            raise CharacterError("Character not found", 404)
        path = self.directory / identifier / "config.json"
        try:
            resolved = path.resolve()
        except (OSError, RuntimeError) as error:
            raise CharacterError("Character path is invalid", 404) from error
        if resolved != path or not resolved.is_relative_to(self.directory):
            raise CharacterError("Character path is outside its storage directory", 404)
        return path

    def _read(self, identifier):
        path = self._path(identifier)
        try:
            with path.open("r", encoding="utf-8-sig") as source:
                text = source.read(1024 * 1024 + 1)
            if len(text) > 1024 * 1024: raise ValueError("Configuration too large")
            data = json.loads(text)
            if not isinstance(data, dict): raise ValueError("Not an object")
            version = data.get("schema_version", 1)
            if type(version) is not int: raise ValueError("Invalid schema version")
            if version > 2:
                raise CharacterError("Character schema version is newer than this application", 409)
            if version not in (1, 2): raise ValueError("Invalid schema version")
            if data.get("id") != identifier: raise ValueError("Mismatched character ID")
            if version == 2 and (not set(CharacterResponse.model_fields).issubset(data)
                                 or data["updated_at"] is None or data["revision"] < 1):
                raise ValueError("Incomplete schema 2 record")
            # Strictly diagnose stored type errors while allowing missing legacy defaults.
            CharacterResponse.model_validate(data, strict=True)
            return data
        except FileNotFoundError as error:
            raise CharacterError("Character not found", 404) from error
        except (OSError, ValueError, TypeError, RecursionError, ValidationError) as error:
            raise CharacterError(f"Character configuration is invalid or unreadable: {identifier}") from error

    def _view(self, data):
        return CharacterResponse.model_validate(data).model_dump(mode="json")

    def get(self, identifier):
        return self._view(self._read(identifier))

    def list(self):
        if not self.directory.exists(): return []
        try:
            result = [self.get(path.name) for path in self.directory.iterdir()
                      if re.fullmatch(r"[0-9a-f]{32}", path.name)
                      and path.is_dir() and (path / "config.json").exists()]
        except OSError as error:
            raise CharacterError("Character directory could not be listed") from error
        return sorted(result, key=lambda data: data["created_at"], reverse=True)

    def _voice(self, value):
        if value is None: return None
        if self.voice_validator is None:
            raise CharacterError("Voice validation is unavailable", 503)
        voice = VoiceConfiguration.model_validate(value)
        return self.voice_validator(voice).model_dump(mode="json")

    def _save(self, path, data):
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", suffix=".tmp",
                                              prefix=".config-", dir=path.parent, delete=False) as target:
                temporary = Path(target.name)
                json.dump(data, target, ensure_ascii=False, indent=2)
                target.flush()
                os.fsync(target.fileno())
            os.replace(temporary, path)
        except (OSError, ValueError) as error:
            raise CharacterError("Character configuration could not be saved") from error
        finally:
            if temporary is not None: temporary.unlink(missing_ok=True)

    def create(self, request: CharacterCreate):
        with _write_lock:
            data = request.model_dump(mode="json")
            data["voice_config"] = self._voice(data["voice_config"])
            identifier = uuid4().hex
            now = datetime.now(timezone.utc).isoformat()
            data.update(id=identifier, created_at=now, updated_at=now, schema_version=2,
                        revision=1, voice_file=None, model_status="not_trained")
            path = self._path(identifier)
            try: path.parent.mkdir(parents=True, exist_ok=False)
            except OSError as error: raise CharacterError("Character directory could not be created") from error
            self._save(path, data)
            return self._view(data)

    def update(self, identifier, request: CharacterPatch):
        changes = request.model_dump(mode="json", exclude_unset=True)
        expected = changes.pop("expected_revision", None)
        if not changes: raise CharacterError("Provide at least one editable field", 422)
        with _write_lock:
            original = self._read(identifier)
            current = self._view(original)
            if expected is not None and expected != current["revision"]:
                raise CharacterError("Character revision changed; reload before saving", 409)
            if "voice_config" in changes:
                changes["voice_config"] = self._voice(changes["voice_config"])
            # Preserve unknown legacy metadata as well as its immutable creation time.
            data = original | current | changes
            data.update(schema_version=2, revision=current["revision"] + 1,
                        updated_at=datetime.now(timezone.utc).isoformat())
            self._save(self._path(identifier), data)
            return self._view(data)
