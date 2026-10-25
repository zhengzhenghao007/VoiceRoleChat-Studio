from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from threading import Lock
from starlette.concurrency import run_in_threadpool

from schemas.transcription import (
    TranscriptionRequest,
    TranscriptionResponse,
)
from services.file_service import save_uploaded_audio
from services.transcription_service import transcribe_audio
from schemas.transcription_job import JobRecord, JobList, TranscriptRecord, JobSubmission
from services.transcription_job_service import TranscriptionJobs, JobError
from config import TRANSCRIPTS_DIR, UPLOAD_DIR, WHISPER_JOB_TIMEOUT
from services.transcript_review_service import TranscriptReviews, ReviewError
from schemas.transcript_review import RecordDocument, RecordList, ReviewCreate, ReviewUpdate

_jobs = None
_jobs_lock = Lock()

def get_jobs():
    global _jobs
    with _jobs_lock:
        if _jobs is None:
            try:
                _jobs = TranscriptionJobs(TRANSCRIPTS_DIR, UPLOAD_DIR, timeout=WHISPER_JOB_TIMEOUT)
            except JobError as error:
                raise HTTPException(error.status_code,str(error)) from error
        return _jobs

def close_jobs():
    global _jobs
    with _jobs_lock:
        if _jobs is not None:
            _jobs.close()
            _jobs = None

def job_call(method,*args):
    try:return method(*args)
    except JobError as error:raise HTTPException(error.status_code,str(error)) from error

def get_reviews():return TranscriptReviews(TRANSCRIPTS_DIR,UPLOAD_DIR)

def review_call(method,*args):
    try:return method(*args)
    except ReviewError as error:raise HTTPException(error.status_code,str(error)) from error


router = APIRouter(
    prefix="/api/transcriptions",
    tags=["Transcriptions"],
)

@router.get('/records',response_model=RecordList)
def list_records(reviews=Depends(get_reviews)):
    return review_call(reviews.list)

@router.get('/records/{identity}',response_model=RecordDocument)
def get_record(identity:str,reviews=Depends(get_reviews)):
    return review_call(reviews.get,identity)

@router.post('/reviews',status_code=201,response_model=RecordDocument)
def create_review(request:ReviewCreate,reviews=Depends(get_reviews)):
    return review_call(reviews.create,request)

@router.get('/reviews/{identity}',response_model=RecordDocument)
def get_review(identity:str,reviews=Depends(get_reviews)):
    doc=review_call(reviews.get,identity)
    if not doc['editable']:raise HTTPException(404,'Review not found')
    return doc

@router.patch('/reviews/{identity}',response_model=RecordDocument)
def update_review(identity:str,request:ReviewUpdate,reviews=Depends(get_reviews)):
    return review_call(reviews.update,identity,request)

@router.post('/jobs',status_code=202,response_model=JobRecord)
def submit_job(request:JobSubmission,jobs=Depends(get_jobs)):
    return job_call(jobs.submit,request.stored_filename,request.language)

@router.get('/jobs',response_model=JobList)
def list_jobs(jobs=Depends(get_jobs)):
    return job_call(jobs.list)

@router.get('/jobs/{identity}',response_model=JobRecord)
def get_job(identity:str,jobs=Depends(get_jobs)):
    return job_call(jobs.get,identity)

@router.post('/jobs/{identity}/cancel',response_model=JobRecord)
def cancel_job(identity:str,jobs=Depends(get_jobs)):
    return job_call(jobs.cancel,identity)

@router.get('/jobs/{identity}/result',response_model=TranscriptRecord)
def get_result(identity:str,jobs=Depends(get_jobs)):
    return job_call(jobs.result,identity)


@router.post(
    "",
    response_model=TranscriptionResponse,
)
def create_transcription(request: TranscriptionRequest):
    return transcribe_audio(
        stored_filename=request.stored_filename,
        language=request.language,
    )


@router.post(
    "/upload",
    response_model=TranscriptionResponse,
)
async def upload_and_transcribe(
    file: UploadFile = File(...),
    language: str | None = None,
):
    upload_result = await save_uploaded_audio(file)

    return await run_in_threadpool(transcribe_audio,
        stored_filename=upload_result["stored_filename"],
        language=language,
    )
