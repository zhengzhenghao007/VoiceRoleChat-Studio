import json
import shutil
import re
import unicodedata
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
    if not isinstance(filename,str) or not filename or filename in {'.','..'} or re.search(r'[\\/:\x00-\x1f]',filename):
        raise HTTPException(status_code=400,detail='Invalid filename.')
    safe_filename = Path(filename).name

    if safe_filename != filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid filename.",
        )

    return safe_filename

def safe_path(path: Path) -> Path:
    path=path.absolute()
    if path.resolve()!=path:
        raise HTTPException(status_code=400,detail='Unsafe dataset input or output path.')
    return path

def annotation_value(value, name):
    if not isinstance(value,str) or not value.strip() or any(ch=='|' or unicodedata.category(ch)=='Cc' or ch in '\u2028\u2029' for ch in value):
        raise HTTPException(status_code=400,detail=name+' must not contain delimiters or control characters.')
    return value.strip()

def remove_created_dataset(path,root=None):
    target=safe_path(path);root=safe_path(DATASETS_DIR if root is None else root)
    if target.parent!=root or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}',target.name):
        raise HTTPException(status_code=500,detail='Refused unsafe dataset cleanup.')
    shutil.rmtree(target,ignore_errors=True)


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
    *, roots=None, cleanup_on_failure=True,
) -> dict:
    characters_root,datasets_root,transcripts_root,uploads_root = roots or (CHARACTERS_DIR,DATASETS_DIR,TRANSCRIPTS_DIR,UPLOAD_DIR)
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,100}',request.character_id):
        raise HTTPException(status_code=400,detail='Invalid character ID.')
    stored_filename = validate_filename(
        request.stored_filename
    )
    transcript_filename = validate_filename(
        request.transcript_filename
    )

    character_config_path = (
        characters_root
        / request.character_id
        / "config.json"
    )
    audio_path = uploads_root / stored_filename
    transcript_path = (
        transcripts_root
        / transcript_filename
    )
    character_config_path=safe_path(character_config_path)
    audio_path=safe_path(audio_path)
    transcript_path=safe_path(transcript_path)

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

    language = annotation_value(transcript_data.get("language", ""),'Language')

    if language not in SUPPORTED_LANGUAGES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Unsupported dataset language: {language}. "
                "Supported languages are zh, ja, en, ko and yue."
            ),
        )

    transcript_text = annotation_value(transcript_data.get("text", ""),'Transcript text')

    if not transcript_text:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The transcript does not contain any text.",
        )

    speaker_name = annotation_value(character_data.get(
        "name",
        request.character_id,
    ),'Speaker name')

    dataset_directory = (
        datasets_root
        / request.dataset_name
    )
    dataset_directory=safe_path(dataset_directory)
    annotation_value(str(dataset_directory/'audio'/audio_path.name),'Annotation audio path')
    audio_directory = dataset_directory / "audio"

    if dataset_directory.exists():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A dataset with this name already exists.",
        )

    dataset_directory.parent.mkdir(parents=True,exist_ok=True)
    dataset_directory.mkdir(exist_ok=False)
    audio_directory.mkdir(exist_ok=False)

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
        if cleanup_on_failure:remove_created_dataset(dataset_directory,datasets_root)

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
        if cleanup_on_failure:remove_created_dataset(dataset_directory,datasets_root)

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Dataset files could not be saved.",
        ) from error

    return metadata
