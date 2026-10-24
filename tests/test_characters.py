"""Versioned atomic character persistence in temporary stores only."""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from pydantic import ValidationError
from schemas.character import CharacterCreate, CharacterPatch, CharacterResponse, VoiceConfiguration
from services.character_service import CharacterService, CharacterError


class CharacterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name) / "characters"
        self.service = CharacterService(self.directory)
        self.request = CharacterCreate(name=" Actor ", system_prompt=" Be kind ")

    def test_create_partial_edit_and_reopen(self):
        self.assertEqual(self.service.list(), [])
        self.assertFalse(self.directory.exists())
        created = self.service.create(self.request)
        self.assertEqual((created["name"], created["schema_version"], created["revision"]), ("Actor", 2, 1))
        edited = self.service.update(created["id"], CharacterPatch(description=" edited ", expected_revision=1))
        self.assertEqual((edited["name"], edited["description"], edited["revision"]), ("Actor", "edited", 2))
        self.assertEqual(edited["created_at"], created["created_at"])
        reopened = CharacterService(self.directory)
        self.assertEqual(reopened.get(created["id"]), edited)
        self.assertEqual(reopened.list(), [edited])
        CharacterResponse.model_validate(edited)

    def test_legacy_read_is_read_only_then_lossless_migration(self):
        identifier = "a" * 32
        path = self.directory / identifier / "config.json"
        path.parent.mkdir(parents=True)
        legacy = self.request.model_dump(exclude={"voice_config"}) | {
            "id": identifier, "created_at": "2020-01-01T00:00:00+00:00", "voice_file": "old.wav",
            "model_status": "trained", "future_metadata": {"keep": True}}
        path.write_text(json.dumps(legacy), encoding="utf-8")
        original, modified = path.read_bytes(), path.stat().st_mtime_ns
        view = self.service.get(identifier)
        self.assertEqual((view["schema_version"], view["revision"], view["voice_config"]), (1, 0, None))
        self.service.list()
        self.assertEqual((path.read_bytes(), path.stat().st_mtime_ns), (original, modified))
        updated = self.service.update(identifier, CharacterPatch(name="New", expected_revision=0))
        self.assertEqual((updated["schema_version"], updated["revision"]), (2, 1))
        stored = json.loads(path.read_text())
        for field in ("created_at", "voice_file", "model_status", "future_metadata"):
            self.assertEqual(stored[field], legacy[field])

    def test_null_blank_unknown_and_immutable_fields_rejected(self):
        for fields in ({"name": None}, {"system_prompt": None}, {"name": "  "},
                       {"system_prompt": " "}, {"id": "x"}, {"created_at": "x"},
                       {"schema_version": 2}, {"expected_revision": -1}, {"expected_revision": True},
                       {"expected_revision": None},
                       {"auto_play_voice": None}, {"description": None}, {"unknown": "x"}):
            with self.subTest(fields=fields), self.assertRaises(ValidationError):
                CharacterPatch(**fields)
        created = self.service.create(self.request)
        for fields in ({}, {"expected_revision": 1}):
            with self.assertRaises(CharacterError) as error:
                self.service.update(created["id"], CharacterPatch(**fields))
            self.assertEqual(error.exception.status_code, 422)

    def test_revision_conflict_and_cross_instance_serialization(self):
        created = self.service.create(self.request)
        other = CharacterService(self.directory)
        def update(index):
            try:
                target = self.service if index == 0 else other
                return target.update(created["id"], CharacterPatch(name=str(index), expected_revision=1))["revision"]
            except CharacterError as error: return error.status_code
        with ThreadPoolExecutor(2) as executor:
            self.assertEqual(sorted(executor.map(update, range(2))), [2, 409])
        self.assertEqual(self.service.get(created["id"])["revision"], 2)

    def test_bad_and_future_schema_never_overwritten(self):
        created = self.service.create(self.request)
        path = self.directory / created["id"] / "config.json"
        for raw, code in ((b'{bad', 500), (b'[]', 500),
                          (json.dumps(created | {"schema_version": 3}).encode(), 409),
                          (json.dumps({key: value for key, value in created.items() if key != "revision"}).encode(), 500),
                          (json.dumps(created | {"revision": "one"}).encode(), 500)):
            path.write_bytes(raw)
            with self.subTest(raw=raw), self.assertRaises(CharacterError) as error:
                self.service.update(created["id"], CharacterPatch(name="New"))
            self.assertEqual(error.exception.status_code, code)
            self.assertEqual(path.read_bytes(), raw)

    def test_atomic_create_and_update_failure(self):
        with patch("services.character_service.os.replace", side_effect=OSError("disk")):
            with self.assertRaises(CharacterError): self.service.create(self.request)
        self.assertEqual(list(self.directory.rglob("*.tmp")), [])
        self.assertEqual(list(self.directory.rglob("config.json")), [])
        created = self.service.create(self.request)
        path = self.directory / created["id"] / "config.json"
        original = path.read_bytes()
        with patch("services.character_service.os.replace", side_effect=OSError("disk")):
            with self.assertRaises(CharacterError):
                self.service.update(created["id"], CharacterPatch(name="New"))
        self.assertEqual(path.read_bytes(), original)
        self.assertEqual(list(self.directory.rglob("*.tmp")), [])

    def test_id_and_resolved_path_containment(self):
        for identifier in ("..", "C:\\outside", "UPPER" * 7, "x", "0" * 32):
            with self.assertRaises(CharacterError) as error: self.service.get(identifier)
            self.assertEqual(error.exception.status_code, 404)
        created = self.service.create(self.request)
        with patch.object(Path, "resolve", return_value=Path(self.temp.name) / "outside"):
            with self.assertRaises(CharacterError): self.service.get(created["id"])

    def test_list_ignores_non_character_backup_directories(self):
        backup = self.directory / "backups" / "config.json"
        backup.parent.mkdir(parents=True)
        backup.write_text("{}", encoding="utf-8")
        self.assertEqual(self.service.list(), [])
        self.assertEqual(backup.read_text(), "{}")

    def test_voice_config_persistence_omission_and_explicit_clear(self):
        voice = VoiceConfiguration(model_id="model", reference_audio="uploads/ref.wav", prompt_text="ref",
                                   prompt_lang="en", text_lang="en")
        calls = []
        service = CharacterService(self.directory, voice_validator=lambda value: calls.append(value) or value)
        created = service.create(self.request.model_copy(update={"voice_config": voice}))
        self.assertEqual(len(calls), 1)
        updated = service.update(created["id"], CharacterPatch(name="New"))
        self.assertEqual(updated["voice_config"], created["voice_config"])
        self.assertEqual(len(calls), 1)
        cleared = service.update(created["id"], CharacterPatch(voice_config=None))
        self.assertIsNone(cleared["voice_config"])
        self.assertIsNone(CharacterService(self.directory).get(created["id"])["voice_config"])


if __name__ == "__main__": unittest.main()
