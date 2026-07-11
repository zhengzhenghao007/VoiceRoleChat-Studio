from fastapi import APIRouter, File, UploadFile

from schemas.transcription import (
    TranscriptionRequest,
    TranscriptionResponse,
)
from services.file_service import save_uploaded_audio
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


@router.post(
    "/upload",
    response_model=TranscriptionResponse,
)
async def upload_and_transcribe(
    file: UploadFile = File(...),
    language: str | None = None,
):
    upload_result = await save_uploaded_audio(file)

    return transcribe_audio(
        stored_filename=upload_result["stored_filename"],
        language=language,
    )