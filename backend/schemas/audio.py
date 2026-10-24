"""Audio asset metadata and finite reference windows."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator


class DecodedAudio(BaseModel):
    model_config = ConfigDict(extra="forbid")
    duration_seconds: float = Field(gt=0, le=1800, allow_inf_nan=False)
    sample_rate: int = Field(ge=8000, le=192000)
    channels: int = Field(ge=1, le=8)
    codec: str = Field(min_length=1, max_length=100)
    processed_samples: int = Field(gt=0, le=64 * 1024 * 1024)
    frame_count: int = Field(gt=0, le=200000)
    source_duration_seconds: float | None = Field(default=None, gt=0, le=1800, allow_inf_nan=False)


class AudioAsset(BaseModel):
    stored_filename: str
    original_filename: str
    file_path: str
    audio_url: str
    file_size: int = Field(ge=0)
    created_at: str
    validation_status: Literal["validated", "uninspected"]
    duration_seconds: float | None = None
    sample_rate: int | None = None
    channels: int | None = None
    codec: str | None = None


class AudioUploadResponse(AudioAsset):
    message: str = "Voice file uploaded successfully."


class AudioListResponse(BaseModel):
    items: list[AudioAsset]
    total: int


class ReferenceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    start_seconds: float = Field(default=0, ge=0, le=1800, allow_inf_nan=False)
    end_seconds: float = Field(gt=0, le=1800, allow_inf_nan=False)

    @model_validator(mode="after")
    def valid_window(self):
        if not 3 <= self.end_seconds - self.start_seconds <= 10:
            raise ValueError("Reference window must be between 3 and 10 seconds")
        return self


class ReferenceResponse(AudioUploadResponse):
    reference_audio: str
