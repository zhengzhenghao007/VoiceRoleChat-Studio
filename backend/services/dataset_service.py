import json
import shutil
from pathlib import Path

from fastapi import HTTPException, status

from config import (
    CHARACTERS_DIR,
    DATASETS_DIR,
    TRANSCRIPTS_DIR,
    UPLOAD_DIR,
)
from schemas.dataset import DatasetBuildRequest


SUPPORTED_LANGUAGES = {
    "zh",
    "ja",
    "en",
    "ko",
    "yue",
}


def validate_filename(filename: str) -> str:
    safe_filename = Path(filename).name

    if safe_filename != filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid filename.",
        )

    return safe_filename


def load_json_file(file_path: Path, error_message: str) -> dict:
    try:
        with file_path.open("r", encoding="utf-8") as file:
            return json.load(file)
    except (OSError, json.JSONDecodeError) as error:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=error_message,
        ) from error


def build_gpt_sovits_dataset(
    request: DatasetBuildRequest,
) -> dict:
    stored_filename = validate_filename(
        request.stored_filename
    )
    transcript_filename = validate_filename(
        request.transcript_filename
    )

    character_config_path = (
        CHARACTERS_DIR
        / request.character_id
        / "config.json"
    )
    audio_path = UPLOAD_DIR / stored_filename
    transcript_path = (
        TRANSCRIPTS_DIR
        / transcript_filename
    )

    if not character_config_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Character not found.",
        )

    if not audio_path.exists() or not audio_path.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Uploaded audio file was not found.",
        )

    if not transcript_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Transcript file was not found.",
        )

    character_data = load_json_file(
        character_config_path,
        "Character configuration could not be read.",
    )
    transcript_data = load_json_file(
        transcript_path,
        "Transcript could not be read.",
    )

    language = transcript_data.get("language", "").strip()

    if language not in SUPPORTED_LANGUAGES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Unsupported dataset language: {language}. "
                "Supported languages are zh, ja, en, ko and yue."
            ),
        )

    transcript_text = transcript_data.get("text", "").strip()

    if not transcript_text:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The transcript does not contain any text.",
        )

    speaker_name = character_data.get(
        "name",
        request.character_id,
    ).strip()

    dataset_directory = (
        DATASETS_DIR
        / request.dataset_name
    )
    audio_directory = dataset_directory / "audio"

    if dataset_directory.exists():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A dataset with this name already exists.",
        )

    audio_directory.mkdir(
        parents=True,
        exist_ok=False,
    )

    copied_audio_path = (
        audio_directory
        / audio_path.name
    )

    try:
        shutil.copy2(
            audio_path,
            copied_audio_path,
        )
    except OSError as error:
        shutil.rmtree(
            dataset_directory,
            ignore_errors=True,
        )

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="The source audio could not be copied.",
        ) from error

    absolute_audio_path = copied_audio_path.resolve()

    annotation_line = (
        f"{absolute_audio_path}"
        f"|{speaker_name}"
        f"|{language}"
        f"|{transcript_text}"
    )

    annotation_path = (
        dataset_directory
        / "transcript.list"
    )

    metadata = {
        "dataset_name": request.dataset_name,
        "character_id": request.character_id,
        "speaker_name": speaker_name,
        "language": language,
        "source_audio": (
            f"datasets/{request.dataset_name}/"
            f"audio/{audio_path.name}"
        ),
        "transcript_file": (
            f"transcripts/{transcript_filename}"
        ),
        "annotation_file": (
            f"datasets/{request.dataset_name}/"
            "transcript.list"
        ),
        "entry_count": 1,
        "total_duration": float(
            transcript_data.get("duration", 0)
        ),
    }

    metadata_path = (
        dataset_directory
        / "dataset.json"
    )

    try:
        annotation_path.write_text(
            annotation_line + "\n",
            encoding="utf-8",
        )

        metadata_path.write_text(
            json.dumps(
                metadata,
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
    except OSError as error:
        shutil.rmtree(
            dataset_directory,
            ignore_errors=True,
        )

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Dataset files could not be saved.",
        ) from error

    return metadata