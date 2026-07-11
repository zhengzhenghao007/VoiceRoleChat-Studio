import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field


router = APIRouter(
    prefix="/api/characters",
    tags=["Characters"],
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
CHARACTERS_DIR = PROJECT_ROOT / "characters"

CHARACTERS_DIR.mkdir(parents=True, exist_ok=True)


class CharacterCreate(BaseModel):
    name: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Display name of the character",
    )

    description: str = Field(
        default="",
        max_length=1000,
        description="Short description of the character",
    )

    system_prompt: str = Field(
        ...,
        min_length=1,
        max_length=10000,
        description="Instructions that define the character",
    )

    reply_language: str = Field(
        default="English",
        max_length=50,
        description="Language used for character replies",
    )

    translation_language: str = Field(
        default="English",
        max_length=50,
        description="Language used for translated text",
    )

    show_original_text: bool = True
    show_translated_text: bool = True
    auto_play_voice: bool = True
    emotional_responses: bool = True


class CharacterResponse(CharacterCreate):
    id: str
    created_at: str
    voice_file: str | None = None
    model_status: str = "not_trained"


def load_character_config(config_path: Path) -> dict:
    try:
        with config_path.open("r", encoding="utf-8") as file:
            return json.load(file)
    except (OSError, json.JSONDecodeError) as error:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Could not read character configuration: {config_path.name}",
        ) from error


@router.post(
    "",
    response_model=CharacterResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_character(character: CharacterCreate):
    character_id = uuid4().hex

    character_directory = CHARACTERS_DIR / character_id
    character_directory.mkdir(parents=True, exist_ok=False)

    created_at = datetime.now(timezone.utc).isoformat()

    character_data = {
        "id": character_id,
        "name": character.name.strip(),
        "description": character.description.strip(),
        "system_prompt": character.system_prompt.strip(),
        "reply_language": character.reply_language.strip(),
        "translation_language": character.translation_language.strip(),
        "show_original_text": character.show_original_text,
        "show_translated_text": character.show_translated_text,
        "auto_play_voice": character.auto_play_voice,
        "emotional_responses": character.emotional_responses,
        "voice_file": None,
        "model_status": "not_trained",
        "created_at": created_at,
    }

    config_path = character_directory / "config.json"

    try:
        with config_path.open("w", encoding="utf-8") as file:
            json.dump(
                character_data,
                file,
                ensure_ascii=False,
                indent=2,
            )
    except OSError as error:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not save character configuration.",
        ) from error

    return character_data


@router.get(
    "",
    response_model=list[CharacterResponse],
)
def list_characters():
    characters: list[dict] = []

    for character_directory in CHARACTERS_DIR.iterdir():
        if not character_directory.is_dir():
            continue

        config_path = character_directory / "config.json"

        if not config_path.exists():
            continue

        characters.append(load_character_config(config_path))

    characters.sort(
        key=lambda item: item.get("created_at", ""),
        reverse=True,
    )

    return characters


@router.get(
    "/{character_id}",
    response_model=CharacterResponse,
)
def get_character(character_id: str):
    config_path = CHARACTERS_DIR / character_id / "config.json"

    if not config_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Character not found.",
        )

    return load_character_config(config_path)