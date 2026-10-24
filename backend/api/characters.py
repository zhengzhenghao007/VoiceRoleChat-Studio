"""Character HTTP API; persistence and validation live in focused services."""
from fastapi import APIRouter, Depends, HTTPException

from api.models import get_model_service
from api.tts import get_synthesis_service, lifecycle
from config import CHARACTERS_DIR, PROJECT_ROOT
from schemas.character import (CharacterCreate, CharacterPatch, CharacterResponse,
                               CharacterSynthesisRequest)
from schemas.tts import SynthesisRequest, SynthesisResult
from services.character_service import CharacterService, CharacterError
from services.synthesis_service import SynthesisService

router = APIRouter(prefix="/api/characters", tags=["Characters"])


def get_character_service(models=Depends(get_model_service)):
    # Binding validation requires no manager, network probe or process creation.
    validator = SynthesisService(None, models, project_root=PROJECT_ROOT)
    return CharacterService(CHARACTERS_DIR, voice_validator=validator.validate_voice)


def character_operation(operation):
    try:
        return lifecycle(operation)
    except CharacterError as error:
        raise HTTPException(status_code=error.status_code, detail=str(error)) from error


@router.post("", response_model=CharacterResponse, status_code=201)
def create_character(character: CharacterCreate, service: CharacterService = Depends(get_character_service)):
    return character_operation(lambda: service.create(character))


@router.get("", response_model=list[CharacterResponse])
def list_characters(service: CharacterService = Depends(get_character_service)):
    return character_operation(service.list)


@router.get("/{character_id}", response_model=CharacterResponse)
def get_character(character_id: str, service: CharacterService = Depends(get_character_service)):
    return character_operation(lambda: service.get(character_id))


@router.patch("/{character_id}", response_model=CharacterResponse)
def update_character(character_id: str, character: CharacterPatch,
                     service: CharacterService = Depends(get_character_service)):
    return character_operation(lambda: service.update(character_id, character))


@router.post("/{character_id}/synthesize", response_model=SynthesisResult)
def synthesize_character(character_id: str, request: CharacterSynthesisRequest,
                         characters: CharacterService = Depends(get_character_service),
                         synthesis: SynthesisService = Depends(get_synthesis_service)):
    def operation():
        character = characters.get(character_id)
        voice = character["voice_config"]
        if voice is None:
            raise CharacterError("Character has no voice binding", 409)
        # Fresh JSON view is the per-request snapshot, independent of later edits.
        settings = {key: value for key, value in voice.items() if key != "version"}
        return synthesis.synthesize(SynthesisRequest(**settings, text=request.text))
    return character_operation(operation)
