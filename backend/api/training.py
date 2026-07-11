from threading import Thread

from fastapi import APIRouter, status

from schemas.training import (
    TrainingJobResponse,
    TrainingRequest,
)
from services.training_service import (
    create_training_job,
    get_training_job,
    list_training_jobs,
)
from workers.training_worker import run_training_job


router = APIRouter(
    prefix="/api/training",
    tags=["Training"],
)


@router.post(
    "/start",
    response_model=TrainingJobResponse,
    status_code=status.HTTP_201_CREATED,
)
def start_training(request: TrainingRequest):
    job_data = create_training_job(request)

    worker_thread = Thread(
        target=run_training_job,
        args=(job_data["job_id"],),
        daemon=True,
    )
    worker_thread.start()

    return job_data


@router.get(
    "",
    response_model=list[TrainingJobResponse],
)
def get_training_jobs():
    return list_training_jobs()


@router.get(
    "/{job_id}",
    response_model=TrainingJobResponse,
)
def get_training_job_status(job_id: str):
    return get_training_job(job_id)