from typing import Any
from types import SimpleNamespace

import pytest
import app.agent.graph as graph_module


@pytest.fixture(autouse=True)
def disable_llm_classifier(monkeypatch):
    def raise_classifier_error(message: str):
        raise RuntimeError("LLM classifier disabled for tests")

    monkeypatch.setattr(
        graph_module,
        "_classify_request_with_llm",
        raise_classifier_error,
    )


class FakeAnswerGradeTool:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def invoke(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(payload)
        is_correct = "정답" in payload["user_answer"] or "맞습니다" in payload["user_answer"]
        return {
            "is_correct": is_correct,
            "score": 100 if is_correct else 60,
            "correct_answer": payload["correct_answer"],
            "explanation": f"{payload['question']} 채점 해설",
            "weakness_tags": [] if is_correct else ["이해 부족"],
            "next_review_action": "다음 복습 액션",
        }


def test_answer_grade_grades_multiple_numbered_answers(monkeypatch):
    fake_tool = FakeAnswerGradeTool()
    monkeypatch.setattr(graph_module, "answer_grade_tool", fake_tool)

    result = graph_module.get_graph().invoke(
        {
            "user_id": "u1",
            "session_id": "multi-grade-1",
            "user_message": "답안 채점:\n1번: 정답입니다.\n2번: 틀린 답입니다.\n3번: 맞습니다.",
            "recent_quiz": _quiz(),
        }
    )

    assert len(fake_tool.calls) == 3
    assert fake_tool.calls[0]["question"] == "문제 1"
    assert fake_tool.calls[0]["correct_answer"] == "정답 1"
    assert fake_tool.calls[0]["user_answer"] == "정답입니다."
    assert fake_tool.calls[1]["question"] == "문제 2"
    assert fake_tool.calls[1]["correct_answer"] == "정답 2"
    assert fake_tool.calls[2]["question"] == "문제 3"
    assert result["tool_result"]["summary"] == {
        "total": 3,
        "correct": 2,
        "average_score": 87,
    }


def test_answer_grade_response_contains_each_question_result_only(
    monkeypatch,
):
    fake_tool = FakeAnswerGradeTool()
    monkeypatch.setattr(graph_module, "answer_grade_tool", fake_tool)

    result = graph_module.get_graph().invoke(
        {
            "user_id": "u1",
            "session_id": "multi-grade-2",
            "user_message": "답안 채점:\n1번: 정답입니다.\n2번: 틀린 답입니다.",
            "recent_quiz": _quiz(),
        }
    )

    response = result["response"]
    assert "[1번]" in response
    assert "[2번]" in response
    assert "점수:" in response
    assert "해설:" in response
    assert "오답 이유:" in response
    assert "복습 계획" not in response
    assert "관련 강의자료를 다시 읽고" not in response


def test_answer_grade_rejects_out_of_range_question_in_bulk(monkeypatch):
    fake_tool = FakeAnswerGradeTool()
    monkeypatch.setattr(graph_module, "answer_grade_tool", fake_tool)

    result = graph_module.get_graph().invoke(
        {
            "user_id": "u1",
            "session_id": "multi-grade-3",
            "user_message": "답안 채점:\n1번: 정답입니다.\n4번: 범위 밖 답입니다.",
            "recent_quiz": _quiz(),
        }
    )

    assert len(fake_tool.calls) == 1
    assert fake_tool.calls[0]["question"] == "문제 1"
    assert "최근 생성된 문제는 3개입니다" in result["response"]
    assert "[4번]" in result["response"]


def test_answer_grade_without_number_defaults_to_first_question(monkeypatch):
    fake_tool = FakeAnswerGradeTool()
    monkeypatch.setattr(graph_module, "answer_grade_tool", fake_tool)

    result = graph_module.get_graph().invoke(
        {
            "user_id": "u1",
            "session_id": "multi-grade-4",
            "user_message": "답안 채점: 정답입니다.",
            "recent_quiz": _quiz(),
        }
    )

    assert len(fake_tool.calls) == 1
    assert fake_tool.calls[0]["question"] == "문제 1"
    assert fake_tool.calls[0]["correct_answer"] == "정답 1"
    assert fake_tool.calls[0]["user_answer"] == "정답입니다."
    assert "[1번]" in result["response"]


def test_removed_weakness_and_review_requests_route_to_fallback():
    assert graph_module.classify_request("약점 분석해줘") == "fallback"
    assert graph_module.classify_request("복습 계획 추천해줘") == "fallback"


def test_rule_classifier_routes_general_questions_to_general_question():
    assert graph_module.classify_request("오늘 날씨 알려줘") == "general_question"
    assert graph_module.classify_request("나는 바보다") == "general_question"


def test_rule_classifier_keeps_tool_requests_on_existing_routes():
    assert graph_module.classify_request("이 PDF 내용으로 문제 내줘") == "quiz_generate"
    assert graph_module.classify_request("TCP 3-way handshake 설명해줘") == "concept_explain"
    assert graph_module.classify_request("1번 답은 SYN 패킷입니다. 채점해줘") == "answer_grade"


def test_empty_or_unclear_request_routes_to_fallback():
    assert graph_module.classify_request("") == "fallback"
    assert graph_module.classify_request("?") == "fallback"


def test_llm_classifier_result_is_used(monkeypatch):
    monkeypatch.setattr(
        graph_module,
        "get_settings",
        lambda: SimpleNamespace(openai_api_key="test-key"),
    )
    monkeypatch.setattr(
        graph_module,
        "_classify_request_with_llm",
        lambda message: graph_module.RequestClassification(
            request_type="general_question",
            confidence=0.95,
            reason="General question",
        ),
    )

    assert graph_module.classify_request("오늘 날씨 알려줘") == "general_question"


def test_llm_classifier_failure_falls_back_to_rules(monkeypatch):
    monkeypatch.setattr(
        graph_module,
        "get_settings",
        lambda: SimpleNamespace(openai_api_key="test-key"),
    )

    assert graph_module.classify_request("예상문제 만들어줘") == "quiz_generate"


def test_general_question_does_not_call_tools_or_retriever(monkeypatch):
    class ToolShouldNotRun:
        def invoke(self, payload: dict[str, Any]) -> dict[str, Any]:
            raise AssertionError("tool should not run for general questions")

    def retrieve_should_not_run(query: str):
        raise AssertionError("retriever should not run for general questions")

    monkeypatch.setattr(graph_module, "concept_explain_tool", ToolShouldNotRun())
    monkeypatch.setattr(graph_module, "quiz_generate_tool", ToolShouldNotRun())
    monkeypatch.setattr(graph_module, "answer_grade_tool", ToolShouldNotRun())
    monkeypatch.setattr(graph_module, "retrieve_context", retrieve_should_not_run)
    monkeypatch.setattr(
        graph_module,
        "_answer_general_question",
        lambda message: "일반 질문 LLM 답변",
    )

    result = graph_module.get_graph().invoke(
        {
            "user_id": "u1",
            "session_id": "general-question-1",
            "user_message": "오늘 날씨 알려줘",
        }
    )

    assert result["request_type"] == "general_question"
    assert result["tool_result"] == {}
    assert result["response"] == "일반 질문 LLM 답변"


def test_answer_general_question_uses_llm_without_tools(monkeypatch):
    class FakeModel:
        def __init__(self, **kwargs) -> None:
            self.kwargs = kwargs

        def invoke(self, messages):
            return SimpleNamespace(content="LLM이 생성한 일반 답변")

    monkeypatch.setattr(
        graph_module,
        "get_settings",
        lambda: SimpleNamespace(
            openai_api_key="test-key",
            openai_chat_model="test-model",
            llm_temperature=0.2,
        ),
    )
    monkeypatch.setattr(graph_module, "ChatOpenAI", FakeModel)

    assert graph_module._answer_general_question("파이썬이 뭐야?") == "LLM이 생성한 일반 답변"


def test_answer_general_question_without_api_key_returns_safe_message(monkeypatch):
    monkeypatch.setattr(
        graph_module,
        "get_settings",
        lambda: SimpleNamespace(openai_api_key=None),
    )

    response = graph_module._answer_general_question("파이썬이 뭐야?")

    assert "OpenAI API Key" in response


def _quiz() -> dict[str, Any]:
    return {
        "topic": "Agentic AI",
        "questions": [
            {
                "question": "문제 1",
                "question_type": "multiple_choice",
                "choices": ["정답 1", "오답"],
                "correct_answer": "정답 1",
                "explanation": "해설 1",
                "source_references": [],
            },
            {
                "question": "문제 2",
                "question_type": "multiple_choice",
                "choices": ["정답 2", "오답"],
                "correct_answer": "정답 2",
                "explanation": "해설 2",
                "source_references": [],
            },
            {
                "question": "문제 3",
                "question_type": "multiple_choice",
                "choices": ["정답 3", "오답"],
                "correct_answer": "정답 3",
                "explanation": "해설 3",
                "source_references": [],
            },
        ],
    }
