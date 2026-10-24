from typing import Literal
from pydantic import BaseModel


class ServiceStatus(BaseModel):
    state: Literal["stopped", "starting", "ready", "unavailable", "failed"]
    managed: bool = False
    pid: int | None = None
    detail: str
