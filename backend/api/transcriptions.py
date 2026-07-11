from fastapi import APIRouter

from schemas.transcription import (
    TranscriptionRequest,
    TranscriptionResponse,
)
from services.transcription_service import transcribe_audio


router = APIRouter(
    prefix="/api/transcriptions",
    tags=["Transcriptions"],
)


@router.post(
    "",
    response_model=TranscriptionResponse,
)
def create_transcription(request: TranscriptionRequest):
    return transcribe_audio(
        stored_filename=request.stored_filename,
        language=request.language,
    )
