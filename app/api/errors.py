import logging

from fastapi import HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.schemas.api import ErrorResponse

logger = logging.getLogger(__name__)


def error_response(
    message: str,
    status_code: int = 500,
    error_code: str = "internal_error",
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content=ErrorResponse(
            error_code=error_code,
            message=message,
        ).model_dump(),
    )


async def http_exception_handler(
    request: Request,
    exc: HTTPException,
) -> JSONResponse:
    return error_response(
        message=str(exc.detail),
        status_code=exc.status_code,
        error_code="http_error",
    )


async def validation_exception_handler(
    request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    return error_response(
        message="요청 형식이 올바르지 않습니다. 입력값을 확인해주세요.",
        status_code=422,
        error_code="validation_error",
    )


async def unhandled_exception_handler(
    request: Request,
    exc: Exception,
) -> JSONResponse:
    logger.exception("Unhandled request error: %s %s", request.method, request.url.path)
    return error_response(
        message="서버 처리 중 문제가 발생했습니다. 잠시 후 다시 시도해주세요.",
        status_code=500,
        error_code="internal_error",
    )
