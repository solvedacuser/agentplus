from fastapi import APIRouter

from app.agent.graph import classify_request, get_graph
from app.api.errors import error_response
from app.rag import is_vector_store_ready
from app.schemas.api import ChatRequest, ChatResponse, ErrorResponse

router = APIRouter(prefix="/api", tags=["chat"])
RAG_REQUIRED_REQUEST_TYPES = {"concept_explain", "quiz_generate"}


@router.post(
    "/chat",
    response_model=ChatResponse,
    responses={500: {"model": ErrorResponse}},
)
def chat(request: ChatRequest):
    request_type = classify_request(request.message)
    if request_type in RAG_REQUIRED_REQUEST_TYPES and not is_vector_store_ready():
        return error_response(
            message="PDF가 아직 인덱싱되지 않았습니다. 먼저 /api/pdfs/index를 실행해주세요.",
            status_code=409,
            error_code="rag_not_indexed",
        )

    try:
        result = get_graph().invoke(
            {
                "user_id": request.user_id,
                "session_id": request.session_id,
                "user_message": request.message,
            }
        )
    except Exception:
        return error_response(
            message="Agent 실행 중 문제가 발생했습니다. 잠시 후 다시 시도해주세요.",
            status_code=500,
            error_code="agent_execution_failed",
        )

    return ChatResponse(
        session_id=request.session_id,
        user_id=request.user_id,
        request_type=result.get("request_type", "fallback"),
        response=result.get("response", ""),
        tool_result=result.get("tool_result", {}),
        weakness_tags=result.get("weakness_tags", []),
    )
