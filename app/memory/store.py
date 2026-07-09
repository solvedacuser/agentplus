from typing import Any, Literal

from pydantic import BaseModel, Field


class MessageRecord(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class SessionMemory(BaseModel):
    session_id: str
    user_id: str = "anonymous"
    messages: list[MessageRecord] = Field(default_factory=list)
    recent_question: str | None = None
    recent_quiz: dict[str, Any] | None = None
    recent_answer: str | None = None
    weakness_tags: list[str] = Field(default_factory=list)
    grading_results: list[dict[str, Any]] = Field(default_factory=list)


_SESSION_STORE: dict[str, SessionMemory] = {}


def get_session_memory(session_id: str, user_id: str = "anonymous") -> SessionMemory:
    if session_id not in _SESSION_STORE:
        _SESSION_STORE[session_id] = SessionMemory(session_id=session_id, user_id=user_id)

    memory = _SESSION_STORE[session_id]
    if user_id and memory.user_id == "anonymous":
        memory.user_id = user_id
    return memory


def append_message(session_id: str, role: Literal["user", "assistant"], content: str) -> None:
    memory = get_session_memory(session_id)
    memory.messages.append(MessageRecord(role=role, content=content))


def remember_question(session_id: str, question: str) -> None:
    memory = get_session_memory(session_id)
    memory.recent_question = question


def remember_quiz(session_id: str, quiz: dict[str, Any]) -> None:
    memory = get_session_memory(session_id)
    memory.recent_quiz = quiz


def remember_answer(session_id: str, answer: str) -> None:
    memory = get_session_memory(session_id)
    memory.recent_answer = answer


def remember_grading_result(session_id: str, grading_result: dict[str, Any]) -> None:
    memory = get_session_memory(session_id)
    memory.grading_results.append(grading_result)
    memory.weakness_tags = _merge_unique(
        memory.weakness_tags,
        _extract_weakness_tags(grading_result),
    )


def _extract_weakness_tags(grading_result: dict[str, Any]) -> list[str]:
    if "weakness_tags" in grading_result:
        return grading_result.get("weakness_tags", [])

    result = grading_result.get("result", {})
    if isinstance(result, dict):
        return result.get("weakness_tags", [])

    return []


def _merge_unique(left: list[str], right: list[str]) -> list[str]:
    merged = list(left)
    for item in right:
        if item not in merged:
            merged.append(item)
    return merged
