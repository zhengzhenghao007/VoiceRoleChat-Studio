"""Small local provider contracts; credentials never enter API schemas."""
from typing import Literal
from pydantic import BaseModel,ConfigDict,Field,field_validator,model_validator


class Message(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    role:Literal['system','user','assistant']
    content:str=Field(min_length=1,max_length=8000)

    @field_validator('content')
    @classmethod
    def nonempty(cls,value):
        if not value.strip():raise ValueError('Empty message')
        return value


class CompletionInput(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    messages:list[Message]=Field(min_length=1,max_length=40)

    @model_validator(mode='after')
    def budget(self):
        if sum(len(item.content) for item in self.messages)>16000:raise ValueError('Message budget exceeded')
        return self


class LLMConfiguration(BaseModel):
    provider:Literal['local_compatible']='local_compatible'
    configured:bool
    model:str|None=None
    credential_configured:bool=False
    error_code:Literal['model_not_configured','configuration_invalid']|None=None


class ModelList(BaseModel):
    models:list[str]=Field(max_length=1000)


class ConnectionResult(BaseModel):
    available:Literal[True]=True
    model:str=Field(max_length=200)
    reply:str=Field(min_length=1,max_length=16000)
