"""Compatibility wrapper shared by voice upload and upload-and-transcribe."""
from fastapi import HTTPException, UploadFile
from config import UPLOAD_DIR
from services.audio_service import AudioService, AudioError


def get_audio_service() -> AudioService:
    return AudioService(UPLOAD_DIR)


async def save_uploaded_audio(file: UploadFile) -> dict:
    try:
        return await get_audio_service().save_upload(file)
    except AudioError as error:
        raise HTTPException(status_code=error.status_code, detail=str(error)) from error
