import re
from typing import Literal
from pydantic import BaseModel,Field,ConfigDict,model_validator
from schemas.segmented_dataset import SegmentDatasetRequest

TrainingEngine=Literal['gpt_sovits','cosyvoice']
TrainingStatus=Literal['queued','preparing','training','completed','failed','cancelled','timed_out','interrupted']
class TrainingOptions(BaseModel):
    model_config=ConfigDict(extra='forbid')
    sovits_epochs:int=Field(default=8,ge=1,le=100,strict=True)
    gpt_epochs:int=Field(default=15,ge=1,le=100,strict=True)
    batch_size:int=Field(default=2,ge=1,le=8,strict=True)
class TrainingRequest(BaseModel):
    model_config=ConfigDict(extra='forbid')
    character_id:str=Field(pattern=r'^[A-Za-z0-9_-]{1,100}$')
    stored_filename:str|None=None
    transcript_filename:str|None=None
    dataset_name:str|None=None
    engine:Literal['gpt_sovits']='gpt_sovits'
    model_name:str=Field(min_length=1,max_length=100)
    training_options:TrainingOptions=Field(default_factory=TrainingOptions)
    @model_validator(mode='after')
    def validate_source(self):
        from services.dataset_service import validate_filename
        if not self.model_name.strip():raise ValueError('Empty model name')
        if self.dataset_name is not None:
            if self.stored_filename is not None or self.transcript_filename is not None:raise ValueError('Mixed training inputs')
            if not re.fullmatch(r'[A-Za-z0-9_-]{1,100}',self.dataset_name):raise ValueError('Invalid dataset name')
            SegmentDatasetRequest.normal_directory(self.dataset_name)
        else:
            if not self.stored_filename or not self.transcript_filename:raise ValueError('Both legacy source filenames required')
            for name in (self.stored_filename,self.transcript_filename):
                try:validate_filename(name)
                except Exception as error:raise ValueError('Invalid input filename') from error
        return self
class TrainingJobResponse(BaseModel):
    training_options:TrainingOptions|None=None
    schema_version:int=0
    decision:Literal['cancelled','timed_out','interrupted']|None=None
    error_code:str|None=None
    job_id:str
    character_id:str
    engine:TrainingEngine
    model_name:str
    stored_filename:str|None=None
    transcript_filename:str|None=None
    dataset_name:str|None=None
    status:TrainingStatus
    progress:int
    current_step:str
    created_at:str
    updated_at:str
    error:str|None=None
    model_path:str|None=None
