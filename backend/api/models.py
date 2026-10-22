from functools import lru_cache
from pathlib import Path

from fastapi import APIRouter, HTTPException, status

from config import PROJECT_ROOT
from schemas.model import (
    VoiceModelInfo,
    VoiceModelListResponse,
)
from services.model_service import AmbiguousModelIdError, ModelService


router = APIRouter(
    prefix="/api/models",
    tags=["Models"],
)


def find_project_root() -> Path:
    """
    Return the data project root, independent of the external tool installation.
    """

    # The external installation may be configured elsewhere or not installed.
    return PROJECT_ROOT


@lru_cache(maxsize=1)
def get_model_service() -> ModelService:
    """
    Singleton ModelService.
    """

    return ModelService(
        project_root=find_project_root()
    )


@router.get(
    "",
    response_model=VoiceModelListResponse,
    summary="List all trained models",
)
def list_models():
    """
    Scan GPT-SoVITS model directories and return all available models.
    """

    service = get_model_service()

    models = service.list_models()

    return VoiceModelListResponse(
        models=models,
        total=len(models),
    )


@router.get(
    "/refresh",
    response_model=VoiceModelListResponse,
    summary="Refresh model registry",
)
def refresh_models():
    """
    Clear cache and rescan model directories.
    """

    get_model_service.cache_clear()

    service = get_model_service()

    models = service.list_models()

    return VoiceModelListResponse(
        models=models,
        total=len(models),
    )


@router.get(
    "/{model_id}",
    response_model=VoiceModelInfo,
    summary="Get model information",
)
def get_model(model_id: str):
    """
    Get a single model.
    """

    service = get_model_service()

    try:
        model = service.get_model(model_id)
    except AmbiguousModelIdError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(error),
        ) from error

    if model is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Model '{model_id}' not found.",
        )

    return model
