import logging
import time

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.api.errors import error_response

logger = logging.getLogger(__name__)


class OperationsMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        start_time = time.perf_counter()
        status_code = 500

        try:
            response = await call_next(request)
            status_code = response.status_code
        except Exception:
            logger.exception(
                "Request failed: method=%s path=%s",
                request.method,
                request.url.path,
            )
            response = error_response(
                message="서버 처리 중 문제가 발생했습니다. 잠시 후 다시 시도해주세요.",
                status_code=500,
                error_code="internal_error",
            )

        process_time_ms = (time.perf_counter() - start_time) * 1000
        response.headers["X-Process-Time-Ms"] = f"{process_time_ms:.2f}"
        logger.info(
            "Request completed: method=%s path=%s status=%s duration_ms=%.2f",
            request.method,
            request.url.path,
            status_code,
            process_time_ms,
        )
        return response
