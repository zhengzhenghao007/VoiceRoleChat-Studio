"""Validated audio upload, library, safe playback and new reference WAVs."""
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse

from schemas.audio import AudioAsset, AudioListResponse, AudioUploadResponse, ReferenceRequest, ReferenceResponse
from services.audio_service import AudioService, AudioError
from services.file_service import get_audio_service

router = APIRouter(prefix="/api/voices", tags=["Voices"])
MEDIA = {".wav":"audio/wav", ".mp3":"audio/mpeg", ".m4a":"audio/mp4", ".flac":"audio/flac", ".ogg":"audio/ogg", ".webm":"audio/webm"}


def audio_operation(operation):
    try: return operation()
    except AudioError as error:
        raise HTTPException(status_code=error.status_code, detail=str(error)) from error


@router.post("/upload", response_model=AudioUploadResponse)
async def upload_voice(file: UploadFile = File(...), service: AudioService = Depends(get_audio_service)):
    try: return await service.save_upload(file)
    except AudioError as error:
        raise HTTPException(status_code=error.status_code, detail=str(error)) from error


@router.get("", response_model=AudioListResponse)
def list_audio(service: AudioService = Depends(get_audio_service)):
    items=audio_operation(service.list)
    return AudioListResponse(items=items,total=len(items))


@router.get("/{stored_filename}", response_model=AudioAsset)
def get_audio(stored_filename: str, service: AudioService = Depends(get_audio_service)):
    return audio_operation(lambda: service.get(stored_filename))


@router.get("/{stored_filename}/audio", response_class=FileResponse)
def play_audio(stored_filename: str, service: AudioService = Depends(get_audio_service)):
    path=audio_operation(lambda: service.audio_path(stored_filename))
    return FileResponse(path,media_type=MEDIA[path.suffix],filename=path.name,
                        content_disposition_type="inline",headers={"X-Content-Type-Options":"nosniff"})


@router.post("/{stored_filename}/inspect", response_model=AudioAsset)
def inspect_audio(stored_filename: str, service: AudioService = Depends(get_audio_service)):
    return audio_operation(lambda: service.inspect(stored_filename))


@router.post("/{stored_filename}/reference", response_model=ReferenceResponse)
def create_reference(stored_filename: str, request: ReferenceRequest,
                     service: AudioService = Depends(get_audio_service)):
    return audio_operation(lambda: service.create_reference(stored_filename,request))
