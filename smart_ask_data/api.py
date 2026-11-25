from __future__ import annotations

from functools import lru_cache

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from smart_ask_data import __version__
from smart_ask_data.config import Settings, load_settings
from smart_ask_data.factory import create_service
from smart_ask_data.health import (
    invalid_data_source_configuration,
    safe_query_backend,
    safe_runtime_label,
    unavailable_data_source,
)
from smart_ask_data.logging import configure_logging
from smart_ask_data.models import AskRequest


class AskBody(BaseModel):
    question: str = Field(min_length=1, max_length=1000)
    debug: bool = False


@lru_cache(maxsize=1)
def get_service():
    return create_service()


def create_api() -> FastAPI:
    try:
        settings = load_settings()
        settings_error = None
    except Exception as exc:  # noqa: BLE001 - preserve a safe health endpoint for configuration failures
        settings = Settings()
        settings_error = exc
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
    def health():
        query_backend = "unknown" if settings_error is not None else safe_query_backend(settings.runtime.query_backend)
        if settings_error is not None:
            data_source = invalid_data_source_configuration()
        else:
            try:
                data_source = get_service().health_check()
            except Exception as exc:  # noqa: BLE001 - health boundary must sanitize startup/driver failures
                data_source = unavailable_data_source(
                    query_backend,
                    settings.trino.read_only if query_backend == "trino" else True,
                    "declared_by_configuration" if query_backend == "trino" else "isolated_demo_database",
                    exc,
                )
        payload = {
            "status": "ok" if data_source.get("status") == "ok" else "unavailable",
            "version": __version__,
            "environment": safe_runtime_label(
                settings.app.environment, {"development", "test", "staging", "production"}
            ),
            "knowledge_backend": safe_runtime_label(settings.runtime.knowledge_backend, {"mock", "qdrant"}),
            "query_backend": query_backend,
            "llm_backend": safe_runtime_label(
                settings.runtime.llm_backend, {"auto", "openai_compatible", "rule"}
            ),
            "data_source": data_source,
        }
        if payload["status"] != "ok":
            return JSONResponse(status_code=503, content=payload)
        return payload

    @app.post("/v1/ask", tags=["ask"])
    def ask(body: AskBody) -> dict:
        if settings_error is not None:
            raise HTTPException(status_code=503, detail="服务配置无效")
        try:
            return get_service().ask(AskRequest(question=body.question, debug=body.debug)).to_dict()
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail="查询处理失败") from exc

    return app


app = create_api()
