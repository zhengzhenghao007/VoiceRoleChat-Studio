"""Offline, serialized synchronous Whisper transcription and atomic results."""
import json
import os
from pathlib import Path
import tempfile
from threading import Lock

from fastapi import HTTPException
from faster_whisper import WhisperModel
from faster_whisper.tokenizer import _LANGUAGE_CODES

from config import (TRANSCRIPTS_DIR, UPLOAD_DIR, WHISPER_COMPUTE_TYPE,
                    WHISPER_DEVICE, WHISPER_MODEL_SIZE)
from schemas.transcription import TranscriptionResponse, TranscriptionSegment
from services.audio_service import AudioError, AudioService, NAME

_model = None
_model_lock = Lock()
_inference_lock = Lock()


def get_whisper_model():
    global _model
    if _model is None:
        with _model_lock:
            if _model is None:
                try:
                    candidate = WhisperModel(WHISPER_MODEL_SIZE, device=WHISPER_DEVICE,
                        compute_type=WHISPER_COMPUTE_TYPE, local_files_only=True)
                except Exception as error:
                    raise HTTPException(503, 'Whisper local model is unavailable. Prepare a complete local model/cache and check WHISPER_MODEL_SIZE, device and compute settings; automatic downloads are disabled.') from error
                _model = candidate
    return _model


def validate_stored_filename(stored_filename: str) -> Path:
    if not isinstance(stored_filename, str) or not NAME.fullmatch(stored_filename):
        raise HTTPException(400, 'Invalid stored filename.')
    try:
        return AudioService(UPLOAD_DIR).audio_path(stored_filename)
    except AudioError as error:
        raise HTTPException(error.status_code, str(error)) from error


def _save_result(data, filename):
    directory = Path(TRANSCRIPTS_DIR).resolve()
    target = directory / filename
    temporary = None
    try:
        directory.mkdir(parents=True, exist_ok=True)
        if target.resolve() != target:
            raise OSError('Unsafe transcript target')
        encoded = json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False).encode('utf-8')
        if len(encoded) > 8 * 1024 * 1024:
            raise ValueError('Transcript exceeds result budget')
        with tempfile.NamedTemporaryFile(dir=directory, suffix='.tmp', delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        # Recheck after staging; this is a local single-user storage contract.
        if target.resolve() != target:
            raise OSError('Unsafe transcript target')
        os.replace(temporary, target)
    except (OSError, ValueError) as error:
        raise HTTPException(500, 'The transcript could not be saved; the previous result was preserved.') from error
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError as error:
                raise HTTPException(500, 'Transcript temporary file cleanup failed; check local storage.') from error


def infer_path(audio_path, stored_filename, language, model):
    """Fully consume and validate inference; caller owns locking/publication."""
    transcript_filename = Path(stored_filename).stem + ".json"
    if language is not None and language not in getattr(model, 'supported_languages', _LANGUAGE_CODES):
        raise HTTPException(422, 'The local model does not support this language.')
    try:
        generator, info = model.transcribe(str(audio_path), language=language,
            beam_size=5, vad_filter=True, word_timestamps=False)
        header = TranscriptionResponse(stored_filename=stored_filename,
            language=info.language, language_probability=info.language_probability,
            duration=info.duration, text='', segments=[],
            transcript_file='transcripts/' + transcript_filename)
        if header.language not in _LANGUAGE_CODES:
            raise ValueError('Invalid detected language')
        rows = []
        characters = 0
        previous_start = 0.0
        for index, row in enumerate(generator):
            if not isinstance(row.text, str):
                raise ValueError('Invalid segment text')
            text = row.text.strip()
            characters += len(text)
            if index >= 100000 or characters > 1024 * 1024:
                raise ValueError('Transcript exceeds segment/text budget')
            # Validate even silent rows so malformed timing is not ignored.
            checked = TranscriptionSegment(start=row.start, end=row.end, text=text)
            if checked.start < previous_start:
                raise ValueError('Segments are not in chronological order')
            previous_start = checked.start
            if checked.end > header.duration + .01:
                raise ValueError('Segment exceeds audio duration')
            if text:
                rows.append(checked.model_dump())
        data = TranscriptionResponse(stored_filename=stored_filename,
            language=header.language, language_probability=header.language_probability,
            duration=header.duration, text=' '.join(row['text'] for row in rows),
            segments=rows, transcript_file='transcripts/' + transcript_filename)
        result = data.model_dump()
    except Exception as error:
        raise HTTPException(500, 'Audio transcription failed; check local audio/model compatibility. No result was published.') from error
    return result


def transcribe_audio(stored_filename: str, language: str | None = None) -> dict:
    if language is not None and language not in _LANGUAGE_CODES:
        raise HTTPException(422, 'Unsupported transcription language code.')
    audio_path = validate_stored_filename(stored_filename)
    with _inference_lock:
        result = infer_path(audio_path, stored_filename, language, get_whisper_model())
        persisted = {key:value for key,value in result.items() if key != 'transcript_file'}
        _save_result(persisted, audio_path.stem + '.json')
        return result
