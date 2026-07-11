from pydantic import BaseModel, Field


class TranscriptionRequest(BaseModel):
    stored_filename: str = Field(
        ...,
        min_length=1,
        description="Filename returned by the voice upload API",
    )

    language: str | None = Field(
        default=None,
        description=(
            "Optional language code such as en, zh or ja. "
            "Leave empty to detect automatically."
        ),
    )


class TranscriptionSegment(BaseModel):
    start: float
    end: float
    text: str


class TranscriptionResponse(BaseModel):
    stored_filename: str
    language: str
    language_probability: float
    duration: float
    text: str
    segments: list[TranscriptionSegment]
    transcript_file: str
    