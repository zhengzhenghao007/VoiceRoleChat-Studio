"""Local provider discovery and an explicit fixed-prompt connection test."""
from functools import lru_cache
from fastapi import APIRouter,Depends,HTTPException
from schemas.llm import LLMConfiguration,ModelList,ConnectionResult,Message
from services.llm_service import LLMService,LLMSettings,LLMError

router=APIRouter(prefix='/api/llm',tags=['Local LLM'])


def failure(error):
    return HTTPException(status_code=error.status_code,detail={'code':error.code})


@lru_cache(maxsize=1)
def _cached_service():
    return LLMService(LLMSettings.load())


async def get_llm_service():
    # Async dependency has no suspension here, preventing parallel cache misses.
    try:return _cached_service()
    except LLMError as error:raise failure(error) from None


@router.get('/config',response_model=LLMConfiguration)
async def configuration():
    try:return _cached_service().configuration()
    except LLMError:return LLMConfiguration(configured=False,error_code='configuration_invalid')


@router.get('/models',response_model=ModelList)
async def models(service:LLMService=Depends(get_llm_service)):
    try:return ModelList(models=await service.models())
    except LLMError as error:raise failure(error) from None


@router.post('/check',response_model=ConnectionResult)
async def check(service:LLMService=Depends(get_llm_service)):
    try:
        reply=await service.complete([Message(role='user',content='Reply with OK.')])
        return ConnectionResult(model=service.settings.model,reply=reply)
    except LLMError as error:raise failure(error) from None
