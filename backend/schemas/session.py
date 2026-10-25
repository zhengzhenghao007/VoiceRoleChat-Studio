"""Versioned sessions and complete message-pair receipts."""
from typing import Literal
from pydantic import BaseModel,ConfigDict,Field,field_validator

ID=r'^[0-9a-f]{32}$'

class Strict(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)

class CharacterSnapshot(Strict):
    name:str=Field(min_length=1,max_length=100)
    revision:int=Field(ge=0)
    system_prompt:str=Field(min_length=1,max_length=10000)
    reply_language:str=Field(min_length=1,max_length=50)
    translation_language:str=Field(min_length=1,max_length=50)

class SessionCreate(Strict):
    character_id:str=Field(pattern=ID)
    title:str=Field(min_length=1,max_length=120)

    @field_validator('title')
    @classmethod
    def title_text(cls,value):
        value=value.strip()
        if not value or any(ord(c)<32 for c in value):raise ValueError('Invalid title')
        return value

class SessionRename(Strict):
    title:str=Field(min_length=1,max_length=120)
    expected_revision:int=Field(ge=1)
    _title=field_validator('title')(SessionCreate.title_text.__func__)

class TurnInput(Strict):
    request_id:str=Field(pattern=ID)
    expected_revision:int=Field(ge=1)
    user_text:str=Field(min_length=1,max_length=8000)
    assistant_text:str=Field(min_length=1,max_length=16000)
    model:str|None=Field(default=None,min_length=1,max_length=200)

    @field_validator('user_text','assistant_text')
    @classmethod
    def nonempty(cls,value):
        if not value.strip():raise ValueError('Empty message')
        return value

class SessionRecord(Strict):
    schema_version:Literal[1]=1
    id:str=Field(pattern=ID)
    revision:int=Field(ge=1)
    character_id:str=Field(pattern=ID)
    character:CharacterSnapshot
    title:str=Field(min_length=1,max_length=120)
    message_count:int=Field(ge=0,le=200)
    created_at:str=Field(min_length=1,max_length=40)
    updated_at:str=Field(min_length=1,max_length=40)

class SessionSummary(Strict):
    id:str=Field(pattern=ID)
    title:str=Field(min_length=1,max_length=120)
    character_id:str=Field(pattern=ID)
    character_name:str=Field(min_length=1,max_length=100)
    revision:int=Field(ge=1)
    message_count:int=Field(ge=0,le=200)
    created_at:str=Field(min_length=1,max_length=40)
    updated_at:str=Field(min_length=1,max_length=40)

class SessionPage(Strict):
    items:list[SessionSummary]=Field(max_length=100)
    total:int=Field(ge=0)

class MessageRecord(Strict):
    id:str=Field(pattern=ID)
    request_id:str=Field(pattern=ID)
    role:Literal['user','assistant']
    content:str=Field(min_length=1,max_length=16000)
    created_at:str=Field(min_length=1,max_length=40)
    model:str|None=Field(default=None,max_length=200)

class TurnReceipt(Strict):
    session_id:str=Field(pattern=ID)
    request_id:str=Field(pattern=ID)
    revision:int=Field(ge=2)
    message_count:int=Field(ge=2,le=200)
    user_message_id:str=Field(pattern=ID)
    assistant_message_id:str=Field(pattern=ID)
