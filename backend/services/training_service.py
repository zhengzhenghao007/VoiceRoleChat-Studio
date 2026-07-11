import json
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from uuid import uuid4

from fastapi import HTTPException, status

from config import (
    CHARACTERS_DIR,
    TRAINING_JOBS_DIR,
    TRANSCRIPTS_DIR,
    UPLOAD_DIR,
)
from schemas.training import TrainingRequest


_job_file_lock = Lock()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def validate_local_filename(filename: str) -> str:
    safe_filename = Path(filename).name

    if safe_filename != filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid filename.",
        )

    return safe_filename


def validate_job_id(job_id: str) -> str:
    safe_job_id = Path(job_id).name

    if safe_job_id != job_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid training job ID.",
        )

    return safe_job_id


def get_job_path(job_id: str) -> Path:
    safe_job_id = validate_job_id(job_id)
    return TRAINING_JOBS_DIR / f"{safe_job_id}.json"


def validate_training_inputs(request: TrainingRequest) -> None:
    character_config = (
        CHARACTERS_DIR
        / request.character_id
        / "config.json"
    )

    if not character_config.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Character not found.",
        )

    stored_filename = validate_local_filename(
        request.stored_filename
    )

    transcript_filename = validate_local_filename(
        request.transcript_filename
    )

    audio_path = UPLOAD_DIR / stored_filename
    transcript_path = TRANSCRIPTS_DIR / transcript_filename

    if not audio_path.exists() or not audio_path.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Uploaded audio file was not found.",
        )

    if not transcript_path.exists() or not transcript_path.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Transcript file was not found.",
        )


def save_training_job(job_data: dict) -> None:
    job_path = get_job_path(job_data["job_id"])
    temporary_path = job_path.with_suffix(".tmp")

    try:
        with _job_file_lock:
            with temporary_path.open(
                "w",
                encoding="utf-8",
            ) as file:
                json.dump(
                    job_data,
                    file,
                    ensure_ascii=False,
                    indent=2,
                )

            temporary_path.replace(job_path)

    except OSError as error:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Training job could not be saved.",
        ) from error


def create_training_job(request: TrainingRequest) -> dict:
    validate_training_inputs(request)

    current_time = utc_now()
    job_id = uuid4().hex

    job_data = {
        "job_id": job_id,
        "character_id": request.character_id,
        "engine": request.engine,
        "model_name": request.model_name.strip(),
        "stored_filename": request.stored_filename,
        "transcript_filename": request.transcript_filename,
        "status": "queued",
        "progress": 0,
        "current_step": "Waiting to start",
        "created_at": current_time,
        "updated_at": current_time,
        "error": None,
        "model_path": None,
    }

    save_training_job(job_data)

    return job_data


def get_training_job(job_id: str) -> dict:
    job_path = get_job_path(job_id)

    if not job_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Training job not found.",
        )

    try:
        with _job_file_lock:
            with job_path.open("r", encoding="utf-8") as file:
                return json.load(file)

    except (OSError, json.JSONDecodeError) as error:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Training job could not be read.",
        ) from error


def update_training_job(
    job_id: str,
    *,
    job_status: str | None = None,
    progress: int | None = None,
    current_step: str | None = None,
    error: str | None = None,
    model_path: str | None = None,
) -> dict:
    job_data = get_training_job(job_id)

    if job_status is not None:
        job_data["status"] = job_status

    if progress is not None:
        job_data["progress"] = max(0, min(progress, 100))

    if current_step is not None:
        job_data["current_step"] = current_step

    if error is not None:
        job_data["error"] = error

    if model_path is not None:
        job_data["model_path"] = model_path

    job_data["updated_at"] = utc_now()

    save_training_job(job_data)

    return job_data


def list_training_jobs() -> list[dict]:
    jobs: list[dict] = []

    for job_path in TRAINING_JOBS_DIR.glob("*.json"):
        try:
            with _job_file_lock:
                with job_path.open(
                    "r",
                    encoding="utf-8",
                ) as file:
                    jobs.append(json.load(file))
        except (OSError, json.JSONDecodeError):
            continue

    jobs.sort(
        key=lambda item: item.get("created_at", ""),
        reverse=True,
    )

    return jobs