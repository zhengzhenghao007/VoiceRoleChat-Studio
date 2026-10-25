"""Bounded role-chat jobs; no provider credentials or mutable prompts in routes."""
from functools import lru_cache
from fastapi import APIRouter,Depends,HTTPException
from config import SESSIONS_DIR
from api.llm import _cached_service
from schemas.reply import ReplyRequest,ReplyState
from services.session_service import SessionService,SessionError
from services.llm_service import LLMError
from services.reply_service import ReplyManager,ReplyError

router=APIRouter(prefix='/api/sessions',tags=['Text replies'])

@lru_cache(maxsize=1)
def _cached_manager():return ReplyManager(SessionService(SESSIONS_DIR),_cached_service)

async def get_reply_manager():return _cached_manager()

async def close_reply_manager():
    if _cached_manager.cache_info().currsize:
        await _cached_manager().close();_cached_manager.cache_clear()

async def operation(action):
    try:return await action()
    except (ReplyError,SessionError,LLMError) as error:
        raise HTTPException(status_code=error.status_code,detail={'code':error.code}) from None

@router.post('/{identity}/replies',response_model=ReplyState,status_code=202)
async def begin(identity:str,request:ReplyRequest,manager:ReplyManager=Depends(get_reply_manager)):
    return await operation(lambda:manager.begin(identity,request))

@router.get('/{identity}/replies/{request_id}',response_model=ReplyState)
async def status(identity:str,request_id:str,manager:ReplyManager=Depends(get_reply_manager)):
    return await operation(lambda:manager.get(identity,request_id))

@router.post('/{identity}/replies/{request_id}/cancel',response_model=ReplyState,status_code=202)
async def cancel(identity:str,request_id:str,manager:ReplyManager=Depends(get_reply_manager)):
    return await operation(lambda:manager.cancel(identity,request_id))
