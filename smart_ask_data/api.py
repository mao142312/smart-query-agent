from __future__ import annotations

from functools import lru_cache

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from smart_ask_data import __version__
from smart_ask_data.config import load_settings
from smart_ask_data.factory import create_service
from smart_ask_data.logging import configure_logging
from smart_ask_data.models import AskRequest


class AskBody(BaseModel):
    question: str = Field(min_length=1, max_length=1000)
    debug: bool = False


@lru_cache(maxsize=1)
def get_service():
    return create_service()


def create_api() -> FastAPI:
    settings = load_settings()
    configure_logging(settings.app.log_level)
    app = FastAPI(
        title="Smart Ask Data API",
        description="知识库驱动、逐轮 SQL 评分的智能问数服务",
        version=__version__,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://127.0.0.1:3000", "http://localhost:3000",
            "http://127.0.0.1:5173", "http://localhost:5173",
        ],
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type"],
    )

    @app.get("/health", tags=["system"])
    def health() -> dict:
        return {
            "status": "ok", "version": __version__,
            "environment": settings.app.environment,
            "knowledge_backend": settings.runtime.knowledge_backend,
            "query_backend": settings.runtime.query_backend,
            "llm_backend": settings.runtime.llm_backend,
        }

    @app.post("/v1/ask", tags=["ask"])
    def ask(body: AskBody) -> dict:
        try:
            return get_service().ask(AskRequest(question=body.question, debug=body.debug)).to_dict()
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail="查询处理失败") from exc

    return app


app = create_api()
