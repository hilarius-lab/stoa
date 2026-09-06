"""Stable client-contract primitives shared by all versioned Android endpoints."""
from datetime import datetime
from typing import Literal

from fastapi import Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from .config import TIMEZONE

RetryClass = Literal["never", "immediate", "backoff", "network", "user_action"]


class ClientAPIError(Exception):
    def __init__(self, status_code: int, code: str, message: str,
                 retry_class: RetryClass = "never", details: dict | None = None):
        self.status_code = status_code
        self.code = code
        self.message = message
        self.retry_class = retry_class
        self.details = details or {}
        super().__init__(message)


class ClientErrorEnvelope(BaseModel):
    code: str
    message: str
    retry_class: RetryClass
    request_id: str
    details: dict = Field(default_factory=dict)
    timestamp: datetime


def error_response(request: Request, status_code: int, code: str, message: str,
                   retry_class: RetryClass = "never", details: dict | None = None):
    request_id = getattr(request.state, "request_id", "unknown")
    body = ClientErrorEnvelope(
        code=code, message=message, retry_class=retry_class,
        request_id=request_id, details=details or {}, timestamp=datetime.now(TIMEZONE)
    )
    return JSONResponse(status_code=status_code, content=jsonable_encoder(body))
