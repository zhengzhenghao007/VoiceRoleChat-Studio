"""Character contracts; legacy response defaults do not rewrite stored files."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator

from schemas.tts import VoiceSettings


class VoiceConfiguration(VoiceSettings):
    model_config = ConfigDict(extra="forbid")
    version: Literal[1] = 1

    @field_validator("version", mode="before")
    @classmethod
    def integer_version(cls, value):
        if type(value) is not int:
            raise ValueError("Voice version must be integer 1")
        return value


class CharacterCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=1000)
    system_prompt: str = Field(min_length=1, max_length=10000)
    reply_language: str = Field(default="English", min_length=1, max_length=50)
    translation_language: str = Field(default="English", min_length=1, max_length=50)
    show_original_text: bool = True
    show_translated_text: bool = True
    auto_play_voice: bool = True
    emotional_responses: bool = True
    voice_config: VoiceConfiguration | None = None

    @field_validator("name", "description", "system_prompt", "reply_language", "translation_language", mode="before")
    @classmethod
    def strip_values(cls, value):
        return value.strip() if isinstance(value, str) else value


class CharacterPatch(CharacterCreate):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    system_prompt: str | None = Field(default=None, min_length=1, max_length=10000)
    expected_revision: StrictInt | None = Field(default=None, ge=0)

    @field_validator("name", "system_prompt", "expected_revision", mode="before")
    @classmethod
    def no_explicit_null(cls, value):
        if value is None: raise ValueError("Field cannot be null")
        return value


class CharacterResponse(CharacterCreate):
    model_config = ConfigDict(extra="ignore")
    id: str
    created_at: str
    voice_file: str | None = None
    model_status: str = "not_trained"
    schema_version: Literal[1, 2] = 1
    revision: StrictInt = Field(default=0, ge=0)
    updated_at: str | None = None


class CharacterSynthesisRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=1000)

    @field_validator("text", mode="before")
    @classmethod
    def strip_text(cls, value):
        return value.strip() if isinstance(value, str) else value
