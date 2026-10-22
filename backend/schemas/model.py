from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class VoiceModelInfo(BaseModel):
    id: str
    name: str
    gpt: str | None = None
    sovits: str | None = None
    language: str | None = None
    created_at: datetime | None = None
    status: Literal["ready", "incomplete"]


class VoiceModelListResponse(BaseModel):
    models: list[VoiceModelInfo]
    total: int