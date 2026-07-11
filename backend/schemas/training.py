from typing import Literal

from pydantic import BaseModel, Field


TrainingEngine = Literal[
    "gpt_sovits",
    "cosyvoice",
]


TrainingStatus = Literal[
    "queued",
    "preparing",
    "training",
    "completed",
    "failed",
    "cancelled",
]


class TrainingRequest(BaseModel):
    character_id: str = Field(
        ...,
        min_length=1,
        description="ID of the character to train",
    )

    stored_filename: str = Field(
        ...,
        min_length=1,
        description="Uploaded audio filename",
    )

    transcript_filename: str = Field(
        ...,
        min_length=1,
        description="Generated transcript JSON filename",
    )

    engine: TrainingEngine = Field(
        default="gpt_sovits",
        description="Voice training engine",
    )

    model_name: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Name used for the generated model",
    )


class TrainingJobResponse(BaseModel):
    job_id: str
    character_id: str
    engine: TrainingEngine
    model_name: str
    stored_filename: str
    transcript_filename: str
    status: TrainingStatus
    progress: int
    current_step: str
    created_at: str
    updated_at: str
    error: str | None = None
    model_path: str | None = None