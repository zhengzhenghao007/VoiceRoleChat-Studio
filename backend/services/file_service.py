from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException, UploadFile, status

from config import (
    ALLOWED_AUDIO_EXTENSIONS,
    MAX_AUDIO_FILE_SIZE,
    UPLOAD_DIR,
)


async def save_uploaded_audio(file: UploadFile) -> dict:
    if not file.filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No filename was provided.",
        )

    extension = Path(file.filename).suffix.lower()

    if extension not in ALLOWED_AUDIO_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Unsupported audio format. "
                "Allowed formats: wav, mp3, m4a, flac and ogg."
            ),
        )

    try:
        file_content = await file.read()
    finally:
        await file.close()

    if not file_content:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The uploaded file is empty.",
        )

    if len(file_content) > MAX_AUDIO_FILE_SIZE:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="The uploaded file exceeds the 50 MB limit.",
        )

    stored_filename = f"{uuid4().hex}{extension}"
    file_path = UPLOAD_DIR / stored_filename

    try:
        file_path.write_bytes(file_content)
    except OSError as error:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="The audio file could not be saved.",
        ) from error

    return {
        "message": "Voice file uploaded successfully.",
        "original_filename": file.filename,
        "stored_filename": stored_filename,
        "file_size": len(file_content),
        "file_path": f"uploads/{stored_filename}",
    }