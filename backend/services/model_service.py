from __future__ import annotations

import hashlib
import json
import logging
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path, PureWindowsPath

from config import env_path
from schemas.model import VoiceModelInfo

logger = logging.getLogger(__name__)


class AmbiguousModelIdError(ValueError):
    """A legacy short ID identifies more than one model."""


class ModelService:
    """
    Discovers trained GPT-SoVITS models and pairs GPT and SoVITS weights.

    Supported examples:

    GPT:
        test_character_auto_v3_80a9a003-e15.ckpt
        test_character_japanese_v1-e15.ckpt

    SoVITS:
        test_character_auto_v3_80a9a003_e8_s400.pth
        test_character_japanese_v1_e8_s400.pth
    """

    GPT_SUFFIX = ".ckpt"
    SOVITS_SUFFIX = ".pth"

    GPT_TRAINING_SUFFIX_PATTERN = re.compile(
        r"(?:[-_]e\d+)(?:[-_]s\d+)?$",
        re.IGNORECASE,
    )

    SOVITS_TRAINING_SUFFIX_PATTERN = re.compile(
        r"(?:[-_]e\d+)(?:[-_]s\d+)?$",
        re.IGNORECASE,
    )

    EXPLICIT_ID_PATTERN = re.compile(
        r"^(?P<name>.+)_(?P<id>[0-9a-fA-F]{8})$"
    )

    LANGUAGE_PATTERNS = {
        "ja": (
            "japanese",
            "_ja",
            "-ja",
            "jp",
        ),
        "zh": (
            "chinese",
            "mandarin",
            "_zh",
            "-zh",
            "中文",
        ),
        "en": (
            "english",
            "_en",
            "-en",
        ),
        "ko": (
            "korean",
            "_ko",
            "-ko",
            "kr",
        ),
    }

    def __init__(
        self,
        project_root: Path,
        gpt_weights_dir: Path | None = None,
        sovits_weights_dir: Path | None = None,
    ) -> None:
        self.project_root = project_root.resolve()
        tool_root = env_path("GPT_SOVITS_ROOT", self.project_root / "GPT-SoVITS", base=self.project_root)

        self.gpt_weights_dir = (
            gpt_weights_dir
            or tool_root
            / "GPT_weights_v2Pro"
        ).resolve()

        self.sovits_weights_dir = (
            sovits_weights_dir
            or tool_root
            / "SoVITS_weights_v2Pro"
        ).resolve()

    def list_models(self) -> list[VoiceModelInfo]:
        return self._registry()[0]

    def _registry(self) -> tuple[list[VoiceModelInfo], set[str]]:
        gpt_files = self._scan_files(
            self.gpt_weights_dir,
            self.GPT_SUFFIX,
        )

        sovits_files = self._scan_files(
            self.sovits_weights_dir,
            self.SOVITS_SUFFIX,
        )

        gpt_models = self._group_weights(gpt_files)
        sovits_models = self._group_weights(sovits_files)

        all_keys = sorted(set(gpt_models) | set(sovits_models))

        candidates: list[tuple[str, VoiceModelInfo]] = []

        for model_key in all_keys:
            gpt_file = self._choose_latest_gpt(
                gpt_models.get(model_key, [])
            )

            sovits_file = self._choose_latest_sovits(
                sovits_models.get(model_key, [])
            )

            source_file = gpt_file or sovits_file

            if source_file is None:
                continue

            display_name, model_id = self._extract_name_and_id(
                model_key
            )

            status = (
                "ready"
                if gpt_file is not None and sovits_file is not None
                else "incomplete"
            )

            candidates.append(
                ("training:" + model_key, VoiceModelInfo(
                    id=model_id,
                    name=display_name,
                    gpt=self._relative_path(gpt_file),
                    sovits=self._relative_path(sovits_file),
                    language=self._detect_language(display_name),
                    created_at=self._get_created_at(
                        gpt_file,
                        sovits_file,
                    ),
                    status=status,
                ))
            )

        candidates.extend(self._exported_models(gpt_models, sovits_models))
        counts = Counter(model.id for _, model in candidates)
        ambiguous = {model_id for model_id, count in counts.items() if count > 1}
        # Reserve every legacy ID before allocating expanded IDs. Identity never
        # includes mtimes, absolute workspace locations or directory scan order.
        allocated = set(counts)
        for identity, model in sorted(candidates, key=lambda item: item[0]):
            if model.id in ambiguous:
                base = model.id
                digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()
                length = 8
                expanded = f"{base}-{digest[:length]}"
                while expanded in allocated:
                    length += 1
                    if length > len(digest):
                        raise RuntimeError("Cannot allocate a unique model identity")
                    expanded = f"{base}-{digest[:length]}"
                model.id = expanded
                allocated.add(expanded)
        models = [model for _, model in candidates]
        models.sort(
            key=lambda item: (
                item.status != "ready",
                item.name.lower(),
                item.id,
            )
        )

        return models, ambiguous

    def get_model(self, model_id: str) -> VoiceModelInfo | None:
        normalized_id = model_id.strip().lower()

        models, ambiguous = self._registry()
        if normalized_id in ambiguous:
            raise AmbiguousModelIdError(
                f"Model ID '{normalized_id}' is ambiguous; use an ID from the model list."
            )
        for model in models:
            if model.id.lower() == normalized_id:
                return model

        return None

    def _exported_models(
        self, gpt_models: dict[str, list[Path]], sovits_models: dict[str, list[Path]],
    ) -> list[tuple[str, VoiceModelInfo]]:
        results: list[tuple[str, VoiceModelInfo]] = []
        export_root = self.project_root / "models"
        if not export_root.is_dir():
            return results
        for manifest in sorted(export_root.glob("*/manifest.json")):
            try:
                directory = manifest.parent
                if not directory.resolve().is_relative_to(export_root.resolve()):
                    raise ValueError("export directory escapes model storage")
                # Also reject a linked model storage directory outside the project.
                if not manifest.resolve().is_relative_to(self.project_root):
                    raise ValueError("manifest escapes project")
                if manifest.resolve().parent != directory.resolve():
                    raise ValueError("manifest escapes export directory")
                with manifest.open("rb") as stream:
                    payload = stream.read(1024 * 1024 + 1)
                if len(payload) > 1024 * 1024:
                    raise ValueError("manifest exceeds 1 MiB")
                data = json.loads(payload.decode("utf-8-sig"))
                if not isinstance(data, dict):
                    raise ValueError("manifest must be a JSON object")
                if data.get("job_id") != directory.name:
                    raise ValueError("job_id does not match export directory")
                if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", directory.name):
                    raise ValueError("invalid job_id")
                experiment = data.get("experiment_name")
                if not isinstance(experiment, str) or not experiment.strip() or len(experiment) > 200:
                    raise ValueError("experiment_name must be a nonempty string")
                language = data.get("language")
                if language is not None and not isinstance(language, str):
                    raise ValueError("language must be a string or null")
                gpt = self._export_weight(data.get("gpt_model"), directory, ".ckpt")
                sovits = self._export_weight(data.get("sovits_model"), directory, ".pth")
                if gpt is None or sovits is None:
                    logger.warning("Incomplete exported model %s: missing weight files", directory.name)
                if gpt is None and sovits is None:
                    continue
                key = self._normalize_model_key(experiment)
                # A name or short ID alone is never evidence of equivalence.
                # Both source references must match files in the same trained
                # experiment; never dereference arbitrary manifest source paths.
                if (self._matches_source(data.get("source_gpt_model"), gpt_models.get(key, []))
                        and self._matches_source(data.get("source_sovits_model"), sovits_models.get(key, []))):
                    continue
                name, model_id = self._extract_name_and_id(key)
                results.append(("export:" + directory.name, VoiceModelInfo(
                    id=model_id, name=name, gpt=self._relative_path(gpt),
                    sovits=self._relative_path(sovits), language=language or self._detect_language(name),
                    created_at=self._get_created_at(gpt, sovits),
                    status="ready" if gpt and sovits else "incomplete",
                )))
            except (OSError, ValueError, RuntimeError) as error:
                logger.warning("Skipping model manifest %s: %s", manifest.name + " in " + manifest.parent.name, error)
        return results

    def _export_weight(self, value: object, directory: Path, suffix: str) -> Path | None:
        if value is None:
            return None
        if not isinstance(value, str) or not value:
            raise ValueError("weight path must be a nonempty string")
        windows = PureWindowsPath(value)
        if ".." in windows.parts or windows.suffix.lower() != suffix or ":" in windows.name:
            raise ValueError("invalid weight path")
        path = Path(value)
        if path.is_absolute() and path.resolve().parent == directory.resolve():
            candidate = path
        elif windows.is_absolute():
            # Legacy exporter stored absolute Windows paths. Only remap the
            # exact models/<job>/<file> tail into this export directory.
            if tuple(windows.parts[-3:-1]) != ("models", directory.name):
                raise ValueError("absolute weight path is outside export directory")
            candidate = directory / windows.name
        elif len(windows.parts) == 1:
            candidate = directory / windows.name
        elif tuple(windows.parts[:-1]) == ("models", directory.name):
            candidate = directory / windows.name
        else:
            raise ValueError("weight path is outside export directory")
        if candidate.resolve().parent != directory.resolve():
            raise ValueError("weight symlink escapes export directory")
        if candidate.exists() and not candidate.is_file():
            raise ValueError("weight path is not a file")
        return candidate.resolve() if candidate.is_file() else None

    def _matches_source(self, value: object, files: list[Path]) -> bool:
        if not isinstance(value, str) or not value:
            return False
        # Compare validated project-relative references lexically; no access to
        # the supplied path is necessary, including when an old drive is gone.
        windows = PureWindowsPath(value)
        if ".." in windows.parts:
            return False
        for file in files:
            resolved = file.resolve()
            if windows.is_absolute() and windows == PureWindowsPath(str(resolved)):
                return True
            if not resolved.is_relative_to(self.project_root):
                continue
            relative = resolved.relative_to(self.project_root)
            if windows.is_absolute():
                expected = (self.project_root.name, *relative.parts)
                if tuple(windows.parts[-len(expected):]) == expected:
                    return True
            elif tuple(windows.parts) == relative.parts:
                return True
        return False

    def _scan_files(
        self,
        directory: Path,
        suffix: str,
    ) -> list[Path]:
        if not directory.exists():
            return []

        return sorted(
            path
            for path in directory.rglob(f"*{suffix}")
            if path.is_file()
        )

    def _group_weights(
        self,
        files: list[Path],
    ) -> dict[str, list[Path]]:
        grouped: dict[str, list[Path]] = {}

        for file_path in files:
            model_key = self._normalize_model_key(file_path.stem)
            grouped.setdefault(model_key, []).append(file_path)

        return grouped

    def _normalize_model_key(self, stem: str) -> str:
        normalized = stem.strip()

        normalized = self.GPT_TRAINING_SUFFIX_PATTERN.sub(
            "",
            normalized,
        )

        normalized = self.SOVITS_TRAINING_SUFFIX_PATTERN.sub(
            "",
            normalized,
        )

        return normalized.rstrip("-_ ")

    def _extract_name_and_id(
        self,
        model_key: str,
    ) -> tuple[str, str]:
        explicit_match = self.EXPLICIT_ID_PATTERN.match(model_key)

        if explicit_match:
            return (
                explicit_match.group("name"),
                explicit_match.group("id").lower(),
            )

        generated_id = hashlib.sha256(
            model_key.encode("utf-8")
        ).hexdigest()[:8]

        return model_key, generated_id

    def _choose_latest_gpt(
        self,
        files: list[Path],
    ) -> Path | None:
        if not files:
            return None

        return max(
            files,
            key=lambda path: (
                self._extract_epoch(path.stem),
                path.stat().st_mtime,
            ),
        )

    def _choose_latest_sovits(
        self,
        files: list[Path],
    ) -> Path | None:
        if not files:
            return None

        return max(
            files,
            key=lambda path: (
                self._extract_step(path.stem),
                self._extract_epoch(path.stem),
                path.stat().st_mtime,
            ),
        )

    @staticmethod
    def _extract_epoch(stem: str) -> int:
        matches = re.findall(
            r"(?:^|[-_])e(\d+)(?:$|[-_])",
            stem,
            flags=re.IGNORECASE,
        )

        if not matches:
            return -1

        return int(matches[-1])

    @staticmethod
    def _extract_step(stem: str) -> int:
        matches = re.findall(
            r"(?:^|[-_])s(\d+)(?:$|[-_])",
            stem,
            flags=re.IGNORECASE,
        )

        if not matches:
            return -1

        return int(matches[-1])

    def _relative_path(
        self,
        file_path: Path | None,
    ) -> str | None:
        if file_path is None:
            return None

        try:
            return file_path.resolve().relative_to(
                self.project_root
            ).as_posix()
        except ValueError:
            return file_path.resolve().as_posix()

    def _detect_language(
        self,
        model_name: str,
    ) -> str | None:
        lowered_name = model_name.lower()

        for language, patterns in self.LANGUAGE_PATTERNS.items():
            if any(
                pattern.lower() in lowered_name
                for pattern in patterns
            ):
                return language

        return None

    @staticmethod
    def _get_created_at(
        gpt_file: Path | None,
        sovits_file: Path | None,
    ) -> datetime | None:
        existing_files = [
            path
            for path in (gpt_file, sovits_file)
            if path is not None and path.exists()
        ]

        if not existing_files:
            return None

        latest_timestamp = max(
            path.stat().st_mtime
            for path in existing_files
        )

        return datetime.fromtimestamp(
            latest_timestamp,
            tz=timezone.utc,
        )
