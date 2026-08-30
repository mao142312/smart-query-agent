from __future__ import annotations

from agent.graph import build_graph
from smart_ask_data.config import ROOT, Settings, load_settings
from smart_ask_data.service import AskDataService
from tools.qdrant_client import LocalKnowledgeClient
from tools.trino_client import SQLiteDemoClient, TrinoClient
from tools.llm_client import OpenAICompatibleLLM


def create_service(settings: Settings | None = None) -> AskDataService:
    settings = settings or load_settings()
    if settings.runtime.knowledge_backend != "mock":
        raise ValueError(f"尚未配置知识库后端：{settings.runtime.knowledge_backend}")
    knowledge_path = ROOT / settings.knowledge.mock_file
    if not knowledge_path.exists():
        knowledge_path = ROOT / "smart_ask_data/resources/mock_knowledge.json"
    knowledge = LocalKnowledgeClient(knowledge_path)
    if settings.runtime.query_backend == "sqlite":
        query = SQLiteDemoClient()
    elif settings.runtime.query_backend == "trino":
        query = TrinoClient(vars(settings.trino))
    else:
        raise ValueError(f"不支持的查询后端：{settings.runtime.query_backend}")
    llm = None
    if settings.runtime.llm_backend in {"auto", "openai_compatible"}:
        api_key = settings.llm.api_key
        if not api_key and settings.runtime.llm_backend == "openai_compatible":
            raise ValueError("启用真实模型前必须在 config/settings.local.yaml 的 llm.api_key 中配置密钥")
        if api_key:
            llm = OpenAICompatibleLLM(
                api_key=api_key, model=settings.llm.model,
                base_url=settings.llm.base_url or None, api_mode=settings.llm.api_mode,
                timeout_seconds=settings.llm.timeout_seconds, thinking=settings.llm.thinking,
            )
    elif settings.runtime.llm_backend != "rule":
        raise ValueError(f"不支持的模型后端：{settings.runtime.llm_backend}")
    graph = build_graph(
        knowledge, query, settings.app.max_retries, llm,
        knowledge_top_n=settings.app.knowledge_top_n,
        intent_threshold=settings.app.intent_retrievability_threshold,
        knowledge_threshold=settings.app.knowledge_candidate_threshold,
        ambiguity_margin=settings.app.knowledge_ambiguity_margin,
    )
    return AskDataService(graph, settings)
