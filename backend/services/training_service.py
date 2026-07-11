import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException, status

from config import (
    CHARACTERS_DIR,
    TRAINING_JOBS_DIR,
    TRANSCRIPTS_DIR,
    UPLOAD_DIR,
)
from schemas.training import TrainingRequest


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

    if not audio_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Uploaded audio file was not found.",
        )

    if not transcript_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Transcript file was not found.",
        )


def save_training_job(job_data: dict) -> None:
    job_path = (
        TRAINING_JOBS_DIR
        / f"{job_data['job_id']}.json"
    )

    try:
        with job_path.open("w", encoding="utf-8") as file:
            json.dump(
                job_data,
                file,
                ensure_ascii=False,
                indent=2,
            )
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
    safe_job_id = Path(job_id).name

    if safe_job_id != job_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid training job ID.",
        )

    job_path = TRAINING_JOBS_DIR / f"{safe_job_id}.json"

    if not job_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Training job not found.",
        )

    try:
        with job_path.open("r", encoding="utf-8") as file:
            return json.load(file)
    except (OSError, json.JSONDecodeError) as error:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Training job could not be read.",
        ) from error


def list_training_jobs() -> list[dict]:
    jobs: list[dict] = []

    for job_path in TRAINING_JOBS_DIR.glob("*.json"):
        try:
            with job_path.open("r", encoding="utf-8") as file:
                jobs.append(json.load(file))
        except (OSError, json.JSONDecodeError):
            continue

    jobs.sort(
        key=lambda item: item.get("created_at", ""),
        reverse=True,
    )

    return jobs