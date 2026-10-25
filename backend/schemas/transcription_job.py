"""Versioned, bounded job and worker protocols (single-process backend)."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator
from schemas.transcription import TranscriptionResponse,TranscriptionRequest

ID=r'^[0-9a-f]{32}$'
SOURCE=r'^[0-9a-f]{32}\.(wav|mp3|m4a|flac|ogg|webm)$'
SHA=r'^[0-9a-f]{64}$'
class StrictModel(BaseModel):
    model_config=ConfigDict(extra='forbid')
class JobSubmission(TranscriptionRequest):
    model_config=ConfigDict(extra='forbid')
class JobRecord(StrictModel):
    schema_version:Literal[1]=1
    id:str=Field(pattern=ID)
    run_nonce:str=Field(pattern=ID)
    source_filename:str=Field(pattern=SOURCE)
    source_sha256:str=Field(pattern=SHA)
    language:str|None=Field(default=None,max_length=3)
    state:Literal['queued','running','succeeded','failed','cancelled','timed_out','interrupted']
    phase:Literal['queued','loading','transcribing','publishing','cancelling','cleanup_failed','finished']
    decision:Literal['cancelled','timed_out']|None=None
    created_at:str=Field(max_length=40)
    updated_at:str=Field(max_length=40)
    error_code:str|None=Field(default=None,max_length=80)
    result_id:str|None=Field(default=None,pattern=ID)
    transcript_file:str|None=Field(default=None,pattern=r'^transcripts/[0-9a-f]{32}\.json$')
class WorkerRequest(StrictModel):
    schema_version:Literal[1]=1
    task_id:str=Field(pattern=ID)
    run_nonce:str=Field(pattern=ID)
    source_filename:str=Field(pattern=SOURCE)
    source_sha256:str=Field(pattern=SHA)
    language:str|None=Field(default=None,max_length=3)
    model_size:str=Field(min_length=1,max_length=4096)
    device:Literal['cpu','cuda','auto']
    compute_type:str=Field(min_length=1,max_length=32)
class Candidate(StrictModel):
    schema_version:Literal[1]=1
    task_id:str=Field(pattern=ID)
    run_nonce:str=Field(pattern=ID)
    source_filename:str=Field(pattern=SOURCE)
    source_sha256:str=Field(pattern=SHA)
    transcript:TranscriptionResponse
class TranscriptRecord(TranscriptionResponse):
    model_config=ConfigDict(extra='forbid')
    schema_version:Literal[2]=2
    id:str=Field(pattern=ID)
    task_id:str=Field(pattern=ID)
    run_nonce:str=Field(pattern=ID)
    source_sha256:str=Field(pattern=SHA)
    revision:Literal[1]=1
    created_at:str=Field(max_length=40)
    @model_validator(mode='after')
    def consistent(self):
        if self.id!=self.task_id or self.transcript_file!='transcripts/'+self.id+'.json':
            raise ValueError('Invalid result identity')
        previous=0.0
        for row in self.segments:
            if row.start<previous:raise ValueError('Segments not chronological')
            previous=row.start
        return self
class JobList(StrictModel):
    items:list[JobRecord]
    diagnostics:list[dict[str,str]]
