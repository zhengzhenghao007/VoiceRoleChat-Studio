"""Independent correction copies; immutable source and versioned review API."""
from typing import Literal
from pydantic import BaseModel,ConfigDict,Field,model_validator
from schemas.transcription import TranscriptionResponse,TranscriptionSegment
from schemas.transcription_job import ID,SHA,SOURCE

class ReviewSegment(TranscriptionSegment):
    model_config=ConfigDict(extra='forbid',str_strip_whitespace=True)
    text:str=Field(min_length=1,max_length=1024*1024)
    @model_validator(mode='after')
    def positive_length(self):
        if self.end<=self.start:raise ValueError('Each segment must have positive duration')
        return self
class ReviewContent(BaseModel):
    model_config=ConfigDict(extra='forbid',str_strip_whitespace=True)
    language:str=Field(min_length=2,max_length=3)
    segments:list[ReviewSegment]=Field(min_length=1,max_length=100000)
    @model_validator(mode='after')
    def ordered_nonoverlapping(self):
        previous=0.0;characters=0
        for row in self.segments:
            if row.start<previous:raise ValueError('Segments must be chronological and nonoverlapping')
            previous=row.end;characters+=len(row.text)
        if characters>1024*1024:raise ValueError('Transcript exceeds text budget')
        return self
class ReviewCreate(ReviewContent):
    source_id:str=Field(pattern=ID)
    expected_source_sha256:str=Field(pattern=SHA)
class ReviewUpdate(ReviewContent):
    expected_revision:int=Field(ge=1,strict=True)
    expected_sha256:str=Field(pattern=SHA)
class ReviewRecord(TranscriptionResponse):
    model_config=ConfigDict(extra='forbid')
    schema_version:Literal[3]=3
    kind:Literal['review']='review'
    id:str=Field(pattern=ID)
    revision:int=Field(ge=1)
    source_id:str=Field(pattern=ID)
    source_sha256:str=Field(pattern=SHA)
    source_revision:int=Field(ge=0)
    stored_filename:str=Field(pattern=SOURCE)
    created_at:str=Field(max_length=40)
    updated_at:str=Field(max_length=40)
    @model_validator(mode='after')
    def valid_review(self):
        content=ReviewContent(language=self.language,segments=[row.model_dump() for row in self.segments])
        if self.text!=' '.join(row.text for row in content.segments):raise ValueError('Review text must match normalized segments')
        if self.transcript_file!='transcripts/'+self.id+'.json':raise ValueError('Wrong review identity')
        return self
class RecordDocument(BaseModel):
    id:str
    kind:Literal['legacy','job','review']
    revision:int
    sha256:str
    editable:bool
    transcript:TranscriptionResponse
    audio_url:str|None=None
    created_at:str
    updated_at:str
    source_id:str|None=None
    source_sha256:str|None=None
class RecordSummary(BaseModel):
    id:str
    kind:Literal['legacy','job','review']
    revision:int
    language:str
    duration:float
    stored_filename:str
    text_preview:str
    segment_count:int
    updated_at:str
class RecordList(BaseModel):
    items:list[RecordSummary]
    diagnostics:list[dict[str,str]]
