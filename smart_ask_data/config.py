from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class AppSettings:
    name: str = "smart-ask-data"
    environment: str = "development"
    max_retries: int = 2
    confidence_threshold: float = 0.65
    max_rows: int = 100
    knowledge_top_n: int = 5
    intent_retrievability_threshold: float = 0.65
    knowledge_candidate_threshold: float = 0.65
    knowledge_ambiguity_margin: float = 0.10
    log_level: str = "INFO"


@dataclass(frozen=True)
class RuntimeSettings:
    query_backend: str = "sqlite"
    knowledge_backend: str = "mock"
    llm_backend: str = "auto"


@dataclass(frozen=True)
class LLMSettings:
    model: str = "deepseek-v4-flash"
    api_key: str = ""
    base_url: str = "https://api.deepseek.com"
    api_mode: str = "chat_completions"
    thinking: str = "enabled"
    timeout_seconds: float = 30.0


@dataclass(frozen=True)
class KnowledgeSettings:
    mock_file: str = "data/mock_knowledge.json"


@dataclass(frozen=True)
class TrinoSettings:
    host: str = "localhost"
    port: int = 8080
    user: str = "smart-ask-data"
    catalog: str = "hive"
    schema: str = "default"
    http_scheme: str = "http"


@dataclass(frozen=True)
class Settings:
    app: AppSettings = field(default_factory=AppSettings)
    runtime: RuntimeSettings = field(default_factory=RuntimeSettings)
    knowledge: KnowledgeSettings = field(default_factory=KnowledgeSettings)
    trino: TrinoSettings = field(default_factory=TrinoSettings)
    llm: LLMSettings = field(default_factory=LLMSettings)


def _yaml_data(path: Path) -> dict[str, Any]:
    try:
        import yaml
    except ImportError:
        return {}
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _merge(result[key], value)
        else:
            result[key] = value
    return result


def load_settings(path: Path | None = None) -> Settings:
    default_path = ROOT / "config/settings.yaml"
    if not default_path.exists():
        default_path = Path(__file__).resolve().parent / "resources/settings.yaml"
    data = _yaml_data(path or default_path)
    if path is None:
        data = _merge(data, _yaml_data(ROOT / "config/settings.local.yaml"))
    app = data.get("app", {})
    runtime = data.get("runtime", {})
    knowledge = data.get("knowledge", {})
    trino = data.get("trino", {})
    llm = data.get("llm", {})
    return Settings(
        app=AppSettings(
            name=os.getenv("SAD_APP_NAME", app.get("name", "smart-ask-data")),
            environment=os.getenv("SAD_ENVIRONMENT", app.get("environment", "development")),
            max_retries=int(os.getenv("SAD_MAX_RETRIES", app.get("max_retries", 2))),
            confidence_threshold=float(os.getenv("SAD_CONFIDENCE_THRESHOLD", app.get("confidence_threshold", 0.65))),
            max_rows=int(os.getenv("SAD_MAX_ROWS", app.get("max_rows", 100))),
            knowledge_top_n=int(os.getenv("SAD_KNOWLEDGE_TOP_N", app.get("knowledge_top_n", 5))),
            intent_retrievability_threshold=float(os.getenv(
                "SAD_INTENT_RETRIEVABILITY_THRESHOLD", app.get("intent_retrievability_threshold", 0.65))),
            knowledge_candidate_threshold=float(os.getenv(
                "SAD_KNOWLEDGE_CANDIDATE_THRESHOLD", app.get("knowledge_candidate_threshold", 0.65))),
            knowledge_ambiguity_margin=float(os.getenv(
                "SAD_KNOWLEDGE_AMBIGUITY_MARGIN", app.get("knowledge_ambiguity_margin", 0.10))),
            log_level=os.getenv("SAD_LOG_LEVEL", app.get("log_level", "INFO")),
        ),
        runtime=RuntimeSettings(
            query_backend=os.getenv("SAD_QUERY_BACKEND", runtime.get("query_backend", "sqlite")),
            knowledge_backend=os.getenv("SAD_KNOWLEDGE_BACKEND", runtime.get("knowledge_backend", "mock")),
            llm_backend=os.getenv("SAD_LLM_BACKEND", runtime.get("llm_backend", "auto")),
        ),
        knowledge=KnowledgeSettings(mock_file=os.getenv("SAD_KNOWLEDGE_FILE", knowledge.get("mock_file", "data/mock_knowledge.json"))),
        trino=TrinoSettings(
            host=os.getenv("SAD_TRINO_HOST", trino.get("host", "localhost")),
            port=int(os.getenv("SAD_TRINO_PORT", trino.get("port", 8080))),
            user=os.getenv("SAD_TRINO_USER", trino.get("user", "smart-ask-data")),
            catalog=os.getenv("SAD_TRINO_CATALOG", trino.get("catalog", "hive")),
            schema=os.getenv("SAD_TRINO_SCHEMA", trino.get("schema", "default")),
            http_scheme=os.getenv("SAD_TRINO_HTTP_SCHEME", trino.get("http_scheme", "http")),
        ),
        llm=LLMSettings(
            model=os.getenv("SAD_LLM_MODEL", llm.get("model", "deepseek-v4-flash")),
            api_key=os.getenv("DEEPSEEK_API_KEY", llm.get("api_key", "")),
            base_url=os.getenv("SAD_LLM_BASE_URL", llm.get("base_url", "https://api.deepseek.com")),
            api_mode=os.getenv("SAD_LLM_API_MODE", llm.get("api_mode", "chat_completions")),
            thinking=os.getenv("SAD_LLM_THINKING", llm.get("thinking", "enabled")),
            timeout_seconds=float(os.getenv("SAD_LLM_TIMEOUT_SECONDS", llm.get("timeout_seconds", 30))),
        ),
    )
