"""Session metadata API. Generation and arbitrary assistant writes are absent."""
from fastapi import APIRouter,Depends,HTTPException,Query
from config import SESSIONS_DIR
from api.characters import get_character_service
from schemas.session import CharacterSnapshot,SessionCreate,SessionRename,SessionRecord,SessionPage,MessageRecord
from services.character_service import CharacterError
from services.session_service import SessionService,SessionError

router=APIRouter(prefix='/api/sessions',tags=['Sessions'])

def get_session_service():return SessionService(SESSIONS_DIR)

def operation(action):
    try:return action()
    except SessionError as error:raise HTTPException(status_code=error.status_code,detail={'code':error.code}) from None
    except CharacterError as error:
        code='character_not_found' if error.status_code==404 else 'character_unavailable'
        raise HTTPException(status_code=error.status_code,detail={'code':code}) from None

@router.post('',response_model=SessionRecord,status_code=201)
def create(request:SessionCreate,store:SessionService=Depends(get_session_service),characters=Depends(get_character_service)):
    def save():
        character=characters.get(request.character_id)
        snapshot=CharacterSnapshot(name=character.name,revision=character.revision,system_prompt=character.system_prompt,reply_language=character.reply_language,translation_language=character.translation_language)
        return store.create(request,snapshot)
    return operation(save)

@router.get('',response_model=SessionPage)
def listing(limit:int=Query(50,ge=1,le=100),offset:int=Query(0,ge=0,le=10000),store:SessionService=Depends(get_session_service)):
    return operation(lambda:store.list(limit,offset))

@router.get('/{identity}',response_model=SessionRecord)
def detail(identity:str,store:SessionService=Depends(get_session_service)):
    return operation(lambda:store.get(identity))

@router.patch('/{identity}',response_model=SessionRecord)
def rename(identity:str,request:SessionRename,store:SessionService=Depends(get_session_service)):
    return operation(lambda:store.rename(identity,request))

@router.get('/{identity}/messages',response_model=list[MessageRecord])
def messages(identity:str,store:SessionService=Depends(get_session_service)):
    return operation(lambda:store.messages(identity))
