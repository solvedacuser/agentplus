from typing import Any, Literal, TypedDict

from pydantic import BaseModel, Field


RequestType = Literal[
    "concept_explain",
    "quiz_generate",
    "answer_grade",
    "general_question",
    "fallback",
]


class AgentState(TypedDict, total=False):
    user_id: str
    session_id: str
    user_message: str
    request_type: RequestType
    recent_question: str
    recent_quiz: dict[str, Any]
    recent_answer: str
    weakness_tags: list[str]
    grading_results: list[dict[str, Any]]
    rag_context: list[dict[str, Any]]
    tool_result: dict[str, Any]
    response: str


class AgentStateModel(BaseModel):
    user_id: str = "anonymous"
    session_id: str = "default"
    user_message: str = Field(min_length=1)
    request_type: RequestType = "fallback"
    recent_question: str | None = None
    recent_quiz: dict[str, Any] | None = None
    recent_answer: str | None = None
    weakness_tags: list[str] = Field(default_factory=list)
    grading_results: list[dict[str, Any]] = Field(default_factory=list)
    rag_context: list[dict[str, Any]] = Field(default_factory=list)
    tool_result: dict[str, Any] = Field(default_factory=dict)
    response: str | None = None
