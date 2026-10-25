"""Durable training API; only supervisor may launch a pipeline."""
from threading import RLock
from fastapi import APIRouter,Depends,HTTPException
from schemas.training import TrainingJobResponse,TrainingRequest
from schemas.training_queue import RuntimeConfig
from services.training_queue import TrainingQueue
from services.training_queue_store import QueueError

router=APIRouter(prefix='/api/training',tags=['Training'])
_queue=None
_admission=False
_queue_lock=RLock()

def start_training_queue():
    global _admission
    with _queue_lock:
        if _queue is not None:raise QueueError('Previous training supervisor has not been closed')
        _admission=True

def close_training_queue():
    global _queue,_admission
    with _queue_lock:
        _admission=False
        if _queue is not None:
            _queue.close();_queue=None

def get_training_queue():
    global _queue
    import config
    with _queue_lock:
        if not _admission:raise HTTPException(status_code=503,detail='Training supervisor is shutting down or unavailable')
        if _queue is None:
            runtime={key:str(getattr(config,key)) for key in RuntimeConfig.model_fields}
            try:_queue=TrainingQueue(config.TRAINING_JOBS_DIR,config.MODELS_DIR,runtime,timeout=config.TRAINING_TASK_TIMEOUT)
            except QueueError as error:raise HTTPException(status_code=503,detail=str(error)) from error
        return _queue


def response(call,*args):
    try:return call(*args)
    except QueueError as error:raise HTTPException(status_code=error.status_code,detail=str(error)) from error

@router.post('/start',response_model=TrainingJobResponse,status_code=201)
def start_training(request:TrainingRequest,queue=Depends(get_training_queue)):
    return response(queue.submit,request)

@router.get('',response_model=list[TrainingJobResponse])
def get_training_jobs(queue=Depends(get_training_queue)):
    return response(queue.list)

@router.get('/diagnostics')
def get_training_diagnostics(queue=Depends(get_training_queue)):
    return response(queue.diagnostics)

@router.post('/{job_id}/cancel',response_model=TrainingJobResponse,status_code=202)
def cancel_training(job_id:str,queue=Depends(get_training_queue)):
    return response(queue.cancel,job_id)

@router.get('/{job_id}',response_model=TrainingJobResponse)
def get_training_job_status(job_id:str,queue=Depends(get_training_queue)):
    return response(queue.get,job_id)
