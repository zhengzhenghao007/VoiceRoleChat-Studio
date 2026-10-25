"""Strict supervisor state and bounded child protocols; canonical state is parent-only."""
from typing import Literal
from pydantic import BaseModel,ConfigDict,Field
from schemas.training import TrainingRequest

ID=r'^[0-9a-f]{32}$';SHA=r'^[0-9a-f]{64}$'
Decision=Literal['cancelled','timed_out','interrupted']
Status=Literal['queued','preparing','training','completed','failed','cancelled','timed_out','interrupted']
class Strict(BaseModel):model_config=ConfigDict(extra='forbid')
class RuntimeConfig(Strict):
    CHARACTERS_DIR:str
    DATASETS_DIR:str
    TRANSCRIPTS_DIR:str
    UPLOAD_DIR:str
    TRAINING_JOBS_DIR:str
    GPT_SOVITS_ROOT:str
    GPT_SOVITS_PYTHON:str
    GPT_SOVITS_BERT_DIR:str
    GPT_SOVITS_HUBERT_DIR:str
    GPT_SOVITS_S1_MODEL:str
    GPT_SOVITS_S2D_MODEL:str
    GPT_SOVITS_S2G_MODEL:str
    GPT_SOVITS_SV_MODEL:str
    GPT_SOVITS_GPU:str=Field(max_length=80)
    TRAINING_COMMAND_TIMEOUT:str=Field(default='21600',max_length=40)
class WorkerRequest(Strict):
    schema_version:Literal[1]=1
    job_id:str=Field(pattern=ID)
    run_nonce:str=Field(pattern=ID)
    request:TrainingRequest
    runtime:RuntimeConfig
    fingerprints:dict[Literal['character','dataset','audio','transcript'],str]
class JobRecord(TrainingRequest):
    schema_version:Literal[1]=1
    job_id:str=Field(pattern=ID)
    run_nonce:str=Field(pattern=ID)
    request_sha256:str=Field(pattern=SHA)
    status:Status='queued'
    progress:int=Field(default=0,ge=0,le=100)
    current_step:str=Field(default='Waiting to start',max_length=200)
    created_at:str=Field(max_length=40)
    updated_at:str=Field(max_length=40)
    decision:Decision|None=None
    error_code:str|None=Field(default=None,max_length=80)
    error:str|None=Field(default=None,max_length=500)
    model_path:str|None=Field(default=None,max_length=100)
    progress_seq:int=Field(default=0,ge=0)
    enqueue_order:int=Field(default=0,ge=0)
class Identity(Strict):
    schema_version:Literal[1]=1
    job_id:str=Field(pattern=ID)
    run_nonce:str=Field(pattern=ID)
    request_sha256:str=Field(pattern=SHA)
class Progress(Identity):
    sequence:int=Field(ge=1)
    status:Literal['preparing','training','failed']
    progress:int=Field(ge=0,le=99)
    current_step:str=Field(max_length=200)
    error_code:Literal['pipeline_failed','input_changed','command_timed_out','command_exit_nonzero','command_cancelled','command_ownership_failed','command_cleanup_failed','command_closed']|None=None
class Candidate(Identity):
    manifest_sha256:str=Field(pattern=SHA)
    gpt_sha256:str=Field(pattern=SHA)
    sovits_sha256:str=Field(pattern=SHA)
