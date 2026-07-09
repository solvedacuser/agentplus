from pathlib import Path
import sys

if __name__ == "__main__":
    project_root = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(project_root))

from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.chat import router as chat_router
from app.api.errors import (
    http_exception_handler,
    unhandled_exception_handler,
    validation_exception_handler,
)
from app.api.health import router as health_router
from app.api.pdfs import router as pdfs_router
from app.api.sessions import router as sessions_router
from app.core.config import get_settings
from app.middleware import OperationsMiddleware


def create_app() -> FastAPI:
    settings = get_settings()
    web_dir = Path(__file__).resolve().parent / "web"
    static_dir = web_dir / "static"

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description="Lecture-material based exam study coach Agent API.",
    )
    app.add_middleware(OperationsMiddleware)
    app.add_exception_handler(HTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)

    app.mount("/static", StaticFiles(directory=static_dir), name="static")

    @app.get("/", include_in_schema=False)
    def web_app() -> FileResponse:
        return FileResponse(web_dir / "index.html")

    app.include_router(health_router)
    app.include_router(chat_router)
    app.include_router(pdfs_router)
    app.include_router(sessions_router)
    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "app.main:app",
        host="127.0.0.1",
        port=settings.port,
        reload=True,
    )
