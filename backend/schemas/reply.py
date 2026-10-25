"""Small reply lifecycle contract; generated text is read from persisted messages."""
from typing import Literal
from pydantic import Field,field_validator
from schemas.session import Strict,ID,TurnReceipt

class ReplyRequest(Strict):
    request_id:str=Field(pattern=ID)
    expected_revision:int=Field(ge=1)
    user_text:str=Field(min_length=1,max_length=8000)

    @field_validator('user_text')
    @classmethod
    def nonempty(cls,value):
        if not value.strip():raise ValueError('Empty message')
        return value

class ReplyState(Strict):
    session_id:str=Field(pattern=ID)
    request_id:str=Field(pattern=ID)
    status:Literal['generating','committing','completed','failed','cancelled']
    receipt:TurnReceipt|None=None
    error_code:str|None=Field(default=None,max_length=80)
