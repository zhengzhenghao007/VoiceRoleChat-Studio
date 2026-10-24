from typing import Literal
from pydantic import BaseModel, Field, validator


class ServiceStatus(BaseModel):
    state: Literal["stopped", "starting", "ready", "unavailable", "failed"]
    managed: bool = False
    pid: int | None = None
    detail: str


Language = Literal["zh", "ja", "en", "ko", "yue", "all_zh", "all_ja", "all_ko", "all_yue", "auto", "auto_yue"]


class VoiceSettings(BaseModel):
    model_id: str = Field(min_length=1, max_length=128)
    text_lang: Language
    reference_audio: str = Field(min_length=1, max_length=1024)
    prompt_text: str = Field(min_length=1, max_length=1000)
    prompt_lang: Language

    @validator("model_id", "reference_audio", "prompt_text", pre=True)
    def strip_text(cls, value):
        return value.strip() if isinstance(value, str) else value

    @validator("reference_audio")
    def safe_reference_text(cls, value):
        if any(ord(char) < 32 or 0xD800 <= ord(char) <= 0xDFFF for char in value):
            raise ValueError("Reference path contains invalid characters")
        return value


class SynthesisRequest(VoiceSettings):
    text: str = Field(min_length=1, max_length=1000)

    @validator("text", pre=True)
    def strip_synthesis_text(cls, value):
        return value.strip() if isinstance(value, str) else value


class SynthesisResult(BaseModel):
    id: str
    model_id: str
    audio_url: str
    sample_rate: int
    duration_seconds: float
