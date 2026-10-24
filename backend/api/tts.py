"""Local service lifecycle; no synthesis or per-request process commands."""
from functools import lru_cache
from threading import Lock

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from schemas.tts import ServiceStatus, SynthesisRequest, SynthesisResult
from api.models import get_model_service
from services.synthesis_service import SynthesisService, SynthesisError
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
    except SynthesisError as error:
        raise HTTPException(status_code=error.status_code, detail=str(error)) from error
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


def get_synthesis_service(manager=Depends(get_tts_service), models=Depends(get_model_service)):
    return SynthesisService(manager, models)


@router.post("/synthesize", response_model=SynthesisResult)
def synthesize(request: SynthesisRequest, service: SynthesisService = Depends(get_synthesis_service)):
    return lifecycle(lambda: service.synthesize(request))


@router.get("/audio/{audio_id}", response_class=FileResponse)
def generated_audio(audio_id: str, service: SynthesisService = Depends(get_synthesis_service)):
    path = lifecycle(lambda: service.audio_path(audio_id))
    return FileResponse(path, media_type="audio/wav", filename=audio_id + ".wav")
