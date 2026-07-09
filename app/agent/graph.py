import re
from typing import Any

from langchain_openai import ChatOpenAI
from langgraph.graph import END, StateGraph
from pydantic import BaseModel, Field

from app.core.config import get_settings
from app.memory import (
    append_message,
    get_session_memory,
    remember_answer,
    remember_grading_result,
    remember_question,
    remember_quiz,
)
from app.rag import retrieve_context
from app.schemas.agent import AgentState, RequestType
from app.tools import answer_grade_tool, concept_explain_tool, quiz_generate_tool


CLASSIFIER_SYSTEM_PROMPT = """
You classify user messages for a lecture-PDF based study coach.

Return only the requested structured output.

Types:
- concept_explain: the user asks to explain, summarize, define, compare, or clarify a study concept.
- quiz_generate: the user asks to create quiz questions, exam questions, practice questions, or expected questions.
- answer_grade: the user asks to grade, score, check, or review their answer.
- general_question: weather, news, stock prices, restaurants, casual chat, general assistant requests, or anything unrelated to the study-coach tasks.
- fallback: too short, empty, or unclear to identify the intended task.

Do not assume the uploaded PDF topic. The PDF may be about any subject.
Classify by the requested task, not by the topic.
"""


class RequestClassification(BaseModel):
    request_type: RequestType
    confidence: float = Field(ge=0, le=1)
    reason: str


def build_study_coach_graph():
    graph = StateGraph(AgentState)

    graph.add_node("analyze_request", analyze_request)
    graph.add_node("concept_explain", run_concept_explain)
    graph.add_node("quiz_generate", run_quiz_generate)
    graph.add_node("answer_grade", run_answer_grade)
    graph.add_node("general_question", run_general_question)
    graph.add_node("fallback", run_fallback)

    graph.set_entry_point("analyze_request")
    graph.add_conditional_edges(
        "analyze_request",
        route_by_request_type,
        {
            "concept_explain": "concept_explain",
            "quiz_generate": "quiz_generate",
            "answer_grade": "answer_grade",
            "general_question": "general_question",
            "fallback": "fallback",
        },
    )

    graph.add_edge("concept_explain", END)
    graph.add_edge("quiz_generate", END)
    graph.add_edge("answer_grade", END)
    graph.add_edge("general_question", END)
    graph.add_edge("fallback", END)

    return graph.compile()


def get_graph():
    return build_study_coach_graph()


def draw_workflow_mermaid() -> str:
    return get_graph().get_graph().draw_mermaid()


def analyze_request(state: AgentState) -> AgentState:
    message = state.get("user_message", "")
    request_type = classify_request(message)
    session_id = state.get("session_id", "default")
    user_id = state.get("user_id", "anonymous")
    memory = get_session_memory(session_id=session_id, user_id=user_id)

    if message:
        append_message(session_id, "user", message)

    recent_question = (
        message
        if request_type in ("concept_explain", "quiz_generate")
        else memory.recent_question or state.get("recent_question", message)
    )

    return {
        **state,
        "request_type": request_type,
        "recent_question": recent_question,
        "recent_quiz": state.get("recent_quiz") or memory.recent_quiz or {},
        "recent_answer": state.get("recent_answer") or memory.recent_answer or "",
        "weakness_tags": _merge_unique(
            state.get("weakness_tags", []),
            memory.weakness_tags,
        ),
        "grading_results": memory.grading_results,
    }


def route_by_request_type(state: AgentState) -> RequestType:
    return state.get("request_type", "fallback")


def run_concept_explain(state: AgentState) -> AgentState:
    question = state.get("recent_question") or state.get("user_message", "")
    rag_context = _safe_retrieve(question)
    result = concept_explain_tool.invoke(
        {
            "user_question": question,
            "rag_context": rag_context,
        }
    )
    session_id = state.get("session_id", "default")
    remember_question(session_id, question)
    append_message(session_id, "assistant", result.get("answer", ""))

    return {
        **state,
        "rag_context": rag_context,
        "tool_result": result,
        "response": result.get("answer", ""),
    }


def run_quiz_generate(state: AgentState) -> AgentState:
    topic = state.get("recent_question") or state.get("user_message", "")
    rag_context = _safe_retrieve(topic)
    result = quiz_generate_tool.invoke(
        {
            "topic": topic,
            "rag_context": rag_context,
            "question_type": "multiple_choice",
            "count": 3,
            "difficulty": "medium",
        }
    )
    response = _format_quiz_response(result)
    session_id = state.get("session_id", "default")
    remember_question(session_id, topic)
    remember_quiz(session_id, result)
    append_message(session_id, "assistant", response)

    return {
        **state,
        "rag_context": rag_context,
        "recent_quiz": result,
        "tool_result": result,
        "response": response,
    }


def run_answer_grade(state: AgentState) -> AgentState:
    message = state.get("user_message", "")
    session_id = state.get("session_id", "default")
    quiz = state.get("recent_quiz", {})
    numbered_answers = _parse_numbered_answers(message)
    grading_items: list[dict[str, Any]] = []
    all_weakness_tags = state.get("weakness_tags", [])

    for question_number, answer in numbered_answers:
        question_item, error_message = _select_quiz_question(quiz, question_number)
        if error_message:
            grading_items.append(
                {
                    "question_number": question_number,
                    "question": None,
                    "user_answer": answer,
                    "error": error_message,
                }
            )
            continue

        question = question_item.get("question") or state.get("recent_question")
        result = answer_grade_tool.invoke(
            {
                "user_answer": answer,
                "question": question,
                "correct_answer": question_item.get("correct_answer"),
                "rag_context": state.get("rag_context", []),
            }
        )
        grading_item = {
            "question_number": question_number,
            "question": question,
            "user_answer": answer,
            "result": result,
        }
        grading_items.append(grading_item)
        remember_grading_result(session_id, grading_item)
        all_weakness_tags = _merge_unique(
            all_weakness_tags,
            result.get("weakness_tags", []),
        )

    remember_answer(session_id, message)
    tool_result = {
        "grading_results": grading_items,
        "summary": _summarize_grading_items(grading_items),
    }
    response = _format_multi_grade_response(grading_items)

    return {
        **state,
        "recent_answer": message,
        "weakness_tags": all_weakness_tags,
        "grading_results": [*state.get("grading_results", []), *grading_items],
        "tool_result": tool_result,
        "response": response,
    }


def run_fallback(state: AgentState) -> AgentState:
    return {
        **state,
        "response": (
            "개념 설명, 예상문제 생성, 답안 채점 중 원하는 작업을 알려주세요."
        ),
    }


def run_general_question(state: AgentState) -> AgentState:
    message = state.get("user_message", "")
    response = _answer_general_question(message)

    return {
        **state,
        "tool_result": {},
        "weakness_tags": state.get("weakness_tags", []),
        "response": response,
    }


def classify_request(message: str) -> RequestType:
    if not message.strip():
        return "fallback"

    settings = get_settings()
    if settings.openai_api_key:
        try:
            return _classify_request_with_llm(message).request_type
        except Exception:
            pass

    return _classify_request_by_rules(message)


def _classify_request_with_llm(message: str) -> RequestClassification:
    settings = get_settings()
    model = ChatOpenAI(
        model=settings.openai_chat_model,
        temperature=0,
        api_key=settings.openai_api_key,
    )
    classifier = model.with_structured_output(RequestClassification)
    result = classifier.invoke(
        [
            ("system", CLASSIFIER_SYSTEM_PROMPT),
            ("human", message),
        ]
    )

    if isinstance(result, RequestClassification):
        return result

    return RequestClassification.model_validate(result)


def _classify_request_by_rules(message: str) -> RequestType:
    normalized = message.lower().strip()

    if not normalized:
        return "fallback"

    if _contains_any(normalized, ["채점", "답안", "grade", "score", "정답 확인"]):
        return "answer_grade"
    if _contains_any(normalized, ["약점", "취약", "오답", "weakness", "복습", "계획", "review", "plan"]):
        return "fallback"
    if _contains_any(normalized, ["문제", "퀴즈", "예상문제", "quiz", "question"]):
        return "quiz_generate"
    if _contains_any(
        normalized,
        ["날씨", "뉴스", "주가", "환율", "맛집", "바보", "멍청", "잡담"],
    ):
        return "general_question"
    if _contains_any(normalized, ["설명", "개념", "알려줘", "explain", "what is"]):
        return "concept_explain"

    return "fallback" if len(normalized) <= 2 else "general_question"


def _contains_any(text: str, keywords: list[str]) -> bool:
    return any(keyword in text for keyword in keywords)


def _merge_unique(left: list[str], right: list[str]) -> list[str]:
    merged = list(left)
    for item in right:
        if item not in merged:
            merged.append(item)
    return merged


def _parse_numbered_answers(message: str) -> list[tuple[int, str]]:
    answers: list[tuple[int, str]] = []
    pattern = re.compile(
        r"^\s*(?:(?:question|q)\s*)?(\d+)\s*(?:번)?\s*[:：]\s*(.+?)\s*$",
        re.IGNORECASE,
    )

    for line in message.splitlines():
        match = pattern.match(line)
        if not match:
            continue
        answer = match.group(2).strip()
        if answer:
            answers.append((int(match.group(1)), answer))

    if answers:
        return answers

    return [(1, _strip_grade_prefix(message))]


def _strip_grade_prefix(message: str) -> str:
    cleaned = re.sub(
        r"^\s*(?:답안\s*)?채점\s*[:：]?\s*",
        "",
        message.strip(),
        flags=re.IGNORECASE,
    )
    return cleaned or message.strip()


def _select_quiz_question(
    quiz: dict[str, Any],
    question_number: int,
) -> tuple[dict[str, Any], str | None]:
    questions = quiz.get("questions") or []
    if not questions:
        return {}, "최근 생성된 문제가 없습니다. 먼저 예상문제를 생성해주세요."

    if question_number < 1 or question_number > len(questions):
        return (
            {},
            (
                f"최근 생성된 문제는 {len(questions)}개입니다. "
                f"1번부터 {len(questions)}번 중 하나를 지정해주세요."
            ),
        )

    return questions[question_number - 1], None


def _latest_quiz_question(quiz: dict[str, Any]) -> tuple[str | None, str | None]:
    question, _ = _select_quiz_question(quiz, 1)
    if not question:
        return None, None

    return question.get("question"), question.get("correct_answer")


def _summarize_grading_items(items: list[dict[str, Any]]) -> dict[str, int]:
    valid_results = [item["result"] for item in items if "result" in item]
    total = len(valid_results)
    correct = sum(1 for result in valid_results if result.get("is_correct"))
    average_score = (
        round(sum(result.get("score", 0) for result in valid_results) / total)
        if total
        else 0
    )

    return {
        "total": total,
        "correct": correct,
        "average_score": average_score,
    }


def _format_multi_grade_response(items: list[dict[str, Any]]) -> str:
    summary = _summarize_grading_items(items)
    lines = [
        f"채점 결과 요약: {summary['total']}문항 중 {summary['correct']}문항 정답",
    ]

    for item in items:
        lines.append("")
        if error := item.get("error"):
            lines.extend(
                [
                    f"[{item.get('question_number')}번]",
                    error,
                ]
            )
            continue

        lines.append(
            _format_single_grade_response(
                item["result"],
                item["question_number"],
                item.get("question") or "",
            )
        )

    return "\n".join(lines)


def _format_single_grade_response(
    result: dict[str, Any],
    question_number: int,
    question: str,
) -> str:
    status = "정답" if result.get("is_correct") else "오답"
    weakness_tags = result.get("weakness_tags") or []
    weakness_text = (
        "\n".join(f"- {tag}" for tag in weakness_tags)
        if weakness_tags
        else "없음"
    )

    return "\n".join(
        [
            f"[{question_number}번]",
            "문제:",
            question or "이전 문제 정보가 없습니다.",
            "",
            f"채점 결과: {status}",
            f"점수: {result.get('score', 0)}점",
            "",
            "해설:",
            result.get("explanation", "채점 해설이 없습니다."),
            "",
            "정답/기준 답안:",
            result.get("correct_answer", "정답 정보가 없습니다."),
            "",
            "오답 이유:",
            weakness_text,
        ]
    )


def _safe_retrieve(query: str) -> list[dict[str, Any]]:
    try:
        return [item.model_dump() for item in retrieve_context(query)]
    except Exception:
        return []


def _answer_general_question(message: str) -> str:
    settings = get_settings()
    if not settings.openai_api_key:
        return (
            "이 질문은 강의 PDF 기반 학습 요청이 아닙니다. "
            "일반 질문 답변에는 OpenAI API Key가 필요합니다."
        )

    try:
        model = ChatOpenAI(
            model=settings.openai_chat_model,
            temperature=settings.llm_temperature,
            api_key=settings.openai_api_key,
        )
        result = model.invoke(
            [
                (
                    "system",
                    "You are a helpful assistant. Answer in Korean. "
                    "Do not claim access to real-time information such as today's "
                    "weather, news, stock prices, or exchange rates. If the question "
                    "requires real-time data, say you cannot verify it without an "
                    "external search tool.",
                ),
                ("human", message),
            ]
        )
        answer = _message_content_to_text(result.content)
        return answer or "일반 질문에 대한 답변을 생성하지 못했습니다."
    except Exception:
        return (
            "일반 질문 답변을 생성하는 중 문제가 발생했습니다. "
            "강의자료 기반 개념 설명, 예상문제 생성, 답안 채점은 계속 사용할 수 있습니다."
        )


def _message_content_to_text(content: Any) -> str:
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and isinstance(item.get("text"), str):
                parts.append(item["text"])
        return "\n".join(part.strip() for part in parts if part.strip())
    return str(content).strip() if content is not None else ""


def _format_quiz_response(result: dict[str, Any]) -> str:
    questions = result.get("questions", [])
    if not questions:
        return "생성된 문제가 없습니다."

    lines: list[str] = []
    for index, question in enumerate(questions, start=1):
        lines.append(f"{index}. {question.get('question', '')}")
        for choice_index, choice in enumerate(question.get("choices", []), start=1):
            lines.append(f"   {choice_index}) {choice}")

    return "\n".join(lines)
