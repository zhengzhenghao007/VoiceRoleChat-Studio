"""Local service lifecycle; no synthesis or per-request process commands."""
from functools import lru_cache
from threading import Lock

from fastapi import APIRouter, Depends, HTTPException

from schemas.tts import ServiceStatus
from services.tts_service import TTSService, ServiceConflict, ServiceTimeout, ServiceUnavailable

router = APIRouter(prefix="/api/tts", tags=["TTS service"])
_service_lock = Lock()


@lru_cache(maxsize=1)
def _cached_service() -> TTSService:
    return TTSService()


def get_tts_service() -> TTSService:
    # lru_cache alone permits duplicate construction on concurrent cache misses.
    with _service_lock:
        return _cached_service()


def close_tts_service():
    with _service_lock:
        if _cached_service.cache_info().currsize:
            _cached_service().close()
            _cached_service.cache_clear()


def lifecycle(operation):
    try:
        return operation()
    except ServiceConflict as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except ServiceTimeout as error:
        raise HTTPException(status_code=504, detail=str(error)) from error
    except ServiceUnavailable as error:
        raise HTTPException(status_code=503, detail=str(error)) from error


@router.get("/service", response_model=ServiceStatus)
def service_status(service: TTSService = Depends(get_tts_service)):
    return service.status()


@router.post("/service/start", response_model=ServiceStatus)
def start_service(service: TTSService = Depends(get_tts_service)):
    return lifecycle(service.start)


@router.post("/service/stop", response_model=ServiceStatus)
def stop_service(service: TTSService = Depends(get_tts_service)):
    return lifecycle(service.stop)
