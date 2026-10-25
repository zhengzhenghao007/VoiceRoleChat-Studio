"""Typed segmented dataset request, candidate and immutable manifest."""
from typing import Literal
from pydantic import BaseModel,ConfigDict,Field,model_validator,field_validator
from schemas.transcription_job import ID,SHA,SOURCE

class Strict(BaseModel):model_config=ConfigDict(extra='forbid')
class SegmentDatasetRequest(Strict):
    character_id:str=Field(pattern=r'^[A-Za-z0-9_-]{1,100}$')
    review_id:str=Field(pattern=ID)
    expected_revision:int=Field(ge=1,strict=True)
    expected_sha256:str=Field(pattern=SHA)
    dataset_name:str=Field(pattern=r'^[A-Za-z0-9_-]{1,100}$')
    @field_validator('dataset_name')
    @classmethod
    def normal_directory(cls,value):
        if value.upper() in {'CON','PRN','AUX','NUL',*(f'COM{i}' for i in range(1,10)),*(f'LPT{i}' for i in range(1,10))}:
            raise ValueError('Reserved directory name')
        return value
class DatasetWindow(Strict):
    start:float=Field(ge=0,le=1800,allow_inf_nan=False)
    end:float=Field(gt=0,le=1800,allow_inf_nan=False)
    @model_validator(mode='after')
    def length(self):
        if not 9600<=round(self.end*32000)-round(self.start*32000)<=960000:
            raise ValueError('Segments must be 0.3 to 30 seconds')
        return self
class DatasetWorkerRequest(Strict):
    schema_version:Literal[1]=1
    task_id:str=Field(pattern=ID)
    run_nonce:str=Field(pattern=ID)
    source_filename:str=Field(pattern=SOURCE)
    source_sha256:str=Field(pattern=SHA)
    windows:list[DatasetWindow]=Field(min_length=1,max_length=1000)
    @model_validator(mode='after')
    def order(self):
        previous=0.0
        for row in self.windows:
            if row.start<previous:raise ValueError('Overlapping or out-of-order windows')
            previous=row.end
        return self
class DatasetClip(Strict):
    index:int=Field(ge=1,le=1000)
    filename:str=Field(pattern=r'^audio/segment_[0-9]{4}\.wav$')
    start_frame:int=Field(ge=0)
    end_frame:int=Field(gt=0)
    frames:int=Field(ge=9600,le=960000)
    duration_seconds:float=Field(ge=.3,le=30,allow_inf_nan=False)
    sha256:str=Field(pattern=SHA)
    peak:float=Field(gt=0,le=1,allow_inf_nan=False)
    rms_dbfs:float=Field(ge=-200,le=0,allow_inf_nan=False)
    warnings:list[Literal['short_clip','long_clip','quiet_clip','clipping']]=Field(max_length=4)
class DatasetWorkerResult(Strict):
    schema_version:Literal[1]=1
    task_id:str=Field(pattern=ID)
    run_nonce:str=Field(pattern=ID)
    source_sha256:str=Field(pattern=SHA)
    source_duration_seconds:float=Field(gt=0,le=1800,allow_inf_nan=False)
    sample_rate:Literal[32000]=32000
    clips:list[DatasetClip]=Field(min_length=1,max_length=1000)
class DatasetErrorProtocol(Strict):
    schema_version:Literal[1]=1
    task_id:str=Field(pattern=ID)
    run_nonce:str=Field(pattern=ID)
    code:Literal['changed_source','invalid_media','resource_limit','source_window','silence','io_error']
    segment:int|None=Field(default=None,ge=1,le=1000)
class ManifestClip(DatasetClip):
    start_seconds:float=Field(ge=0,allow_inf_nan=False)
    end_seconds:float=Field(gt=0,allow_inf_nan=False)
    text:str=Field(min_length=1,max_length=1048576)
class SegmentDatasetManifest(Strict):
    schema_version:Literal[2]=2
    dataset_name:str=Field(pattern=r'^[A-Za-z0-9_-]{1,100}$')
    character_id:str=Field(pattern=r'^[A-Za-z0-9_-]{1,100}$')
    speaker_name:str=Field(min_length=1,max_length=100)
    language:Literal['zh','ja','en','ko','yue']
    review_id:str=Field(pattern=ID)
    review_revision:int=Field(ge=1)
    review_sha256:str=Field(pattern=SHA)
    source_audio:str=Field(pattern=r'^uploads/[0-9a-f]{32}\.(wav|mp3|m4a|flac|ogg|webm)$')
    source_audio_sha256:str=Field(pattern=SHA)
    source_transcript_snapshot:str
    annotation_file:str
    entry_count:int=Field(ge=1,le=1000)
    total_duration:float=Field(gt=0,le=1800,allow_inf_nan=False)
    created_at:str=Field(max_length=40)
    warnings:list[str]=Field(max_length=4000)
    clips:list[ManifestClip]=Field(min_length=1,max_length=1000)
class DatasetList(Strict):
    items:list[dict]
    diagnostics:list[dict[str,str]]
