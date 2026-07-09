from typing import Any

from pydantic import BaseModel, Field

from app.memory.store import MessageRecord
from app.schemas.agent import RequestType


class ErrorResponse(BaseModel):
    success: bool = False
    error_code: str
    message: str


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=1000)
    session_id: str = Field(default="default", min_length=1, max_length=100)
    user_id: str = Field(default="anonymous", min_length=1, max_length=100)


class ChatResponse(BaseModel):
    success: bool = True
    session_id: str
    user_id: str
    request_type: RequestType
    response: str
    tool_result: dict[str, Any] = Field(default_factory=dict)
    weakness_tags: list[str] = Field(default_factory=list)


class PdfIndexRequest(BaseModel):
    pdf_dir: str | None = None


class PdfIndexResponse(BaseModel):
    success: bool = True
    pdf_count: int
    page_count: int
    chunk_count: int
    vector_store_path: str


class SessionStateResponse(BaseModel):
    success: bool = True
    session_id: str
    user_id: str
    messages: list[MessageRecord]
    recent_question: str | None = None
    recent_quiz: dict[str, Any] | None = None
    recent_answer: str | None = None
    weakness_tags: list[str] = Field(default_factory=list)
    grading_results: list[dict[str, Any]] = Field(default_factory=list)
