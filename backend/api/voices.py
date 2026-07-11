from fastapi import APIRouter, File, UploadFile

from services.file_service import save_uploaded_audio


router = APIRouter(
    prefix="/api/voices",
    tags=["Voices"],
)


@router.post("/upload")
async def upload_voice(file: UploadFile = File(...)):
    return await save_uploaded_audio(file)
