from fastapi import APIRouter, status

from schemas.dataset import (
    DatasetBuildRequest,
    DatasetBuildResponse,
)
from services.dataset_service import (
    build_gpt_sovits_dataset,
)


router = APIRouter(
    prefix="/api/datasets",
    tags=["Datasets"],
)


@router.post(
    "/build",
    response_model=DatasetBuildResponse,
    status_code=status.HTTP_201_CREATED,
)
def build_dataset(request: DatasetBuildRequest):
    return build_gpt_sovits_dataset(request)