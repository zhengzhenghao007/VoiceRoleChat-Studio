import json
from pathlib import Path
from threading import Lock

from fastapi import HTTPException, status
from faster_whisper import WhisperModel

from config import (
    TRANSCRIPTS_DIR,
    UPLOAD_DIR,
    WHISPER_COMPUTE_TYPE,
    WHISPER_DEVICE,
    WHISPER_MODEL_SIZE,
)


_model: WhisperModel | None = None
_model_lock = Lock()


def get_whisper_model() -> WhisperModel:
    global _model

    if _model is None:
        with _model_lock:
            if _model is None:
                _model = WhisperModel(
                    WHISPER_MODEL_SIZE,
                    device=WHISPER_DEVICE,
                    compute_type=WHISPER_COMPUTE_TYPE,
                )

    return _model


def validate_stored_filename(stored_filename: str) -> Path:
    safe_filename = Path(stored_filename).name

    if safe_filename != stored_filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid stored filename.",
        )

    audio_path = UPLOAD_DIR / safe_filename

    if not audio_path.exists() or not audio_path.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Uploaded audio file was not found.",
        )

    return audio_path


def transcribe_audio(
    stored_filename: str,
    language: str | None = None,
) -> dict:
    audio_path = validate_stored_filename(stored_filename)

    try:
        model = get_whisper_model()

        segments_generator, info = model.transcribe(
            str(audio_path),
            language=language,
            beam_size=5,
            vad_filter=True,
            word_timestamps=False,
        )

        segments: list[dict] = []
        full_text_parts: list[str] = []

        for segment in segments_generator:
            clean_text = segment.text.strip()

            if not clean_text:
                continue

            segments.append(
                {
                    "start": round(segment.start, 3),
                    "end": round(segment.end, 3),
                    "text": clean_text,
                }
            )

            full_text_parts.append(clean_text)

    except Exception as error:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Audio transcription failed: {error}",
        ) from error

    full_text = " ".join(full_text_parts).strip()

    transcript_data = {
        "stored_filename": stored_filename,
        "language": info.language,
        "language_probability": round(
            info.language_probability,
            4,
        ),
        "duration": round(info.duration, 3),
        "text": full_text,
        "segments": segments,
    }

    transcript_filename = f"{audio_path.stem}.json"
    transcript_path = TRANSCRIPTS_DIR / transcript_filename

    try:
        with transcript_path.open("w", encoding="utf-8") as file:
            json.dump(
                transcript_data,
                file,
                ensure_ascii=False,
                indent=2,
            )
    except OSError as error:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="The transcript could not be saved.",
        ) from error

    transcript_data["transcript_file"] = (
        f"transcripts/{transcript_filename}"
    )

    return transcript_data
