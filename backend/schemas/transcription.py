from pydantic import BaseModel, Field, model_validator


class TranscriptionRequest(BaseModel):
    stored_filename: str = Field(..., min_length=1, max_length=64,
        description='Filename returned by the voice upload API')
    language: str | None = Field(default=None, max_length=3,
        description='Supported Whisper language code such as en, zh or ja; null for automatic detection.')


class TranscriptionSegment(BaseModel):
    start: float = Field(ge=0, allow_inf_nan=False)
    end: float = Field(ge=0, allow_inf_nan=False)
    text: str = Field(max_length=1024 * 1024)

    @model_validator(mode='after')
    def valid_interval(self):
        if self.end < self.start:
            raise ValueError('Segment end precedes start')
        return self


class TranscriptionResponse(BaseModel):
    stored_filename: str
    language: str = Field(min_length=2, max_length=3)
    language_probability: float = Field(ge=0, le=1, allow_inf_nan=False)
    duration: float = Field(ge=0, allow_inf_nan=False)
    text: str = Field(max_length=1024 * 1024)
    segments: list[TranscriptionSegment] = Field(max_length=100000)
    transcript_file: str

    @model_validator(mode='after')
    def segments_within_duration(self):
        if any(row.end > self.duration + .01 for row in self.segments):
            raise ValueError('Segment exceeds audio duration')
        return self
