from pydantic import BaseModel, Field


class DatasetBuildRequest(BaseModel):
    character_id: str = Field(
        ...,
        min_length=1,
        description="Character ID used as the speaker",
    )

    stored_filename: str = Field(
        ...,
        min_length=1,
        description="Uploaded audio filename",
    )

    transcript_filename: str = Field(
        ...,
        min_length=1,
        description="Whisper transcript JSON filename",
    )

    dataset_name: str = Field(
        ...,
        min_length=1,
        max_length=100,
        pattern=r"^[A-Za-z0-9_-]+$",
        description=(
            "Dataset folder name using letters, numbers, "
            "underscores or hyphens"
        ),
    )


class DatasetBuildResponse(BaseModel):
    dataset_name: str
    character_id: str
    speaker_name: str
    language: str
    source_audio: str
    transcript_file: str
    annotation_file: str
    entry_count: int
    total_duration: float
    