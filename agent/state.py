from __future__ import annotations

from typing import Any, TypedDict


class AgentState(TypedDict, total=False):
    request_id: str
    trace_log_dir: str
    llm_used: bool
    llm_error: str
    llm_request: dict[str, Any]
    llm_response: dict[str, Any] | None
    question: str
    intent: dict[str, Any]
    intent_llm_request: dict[str, Any]
    intent_llm_response: dict[str, Any] | None
    retrievability_validation: dict[str, Any]
    retrieval_query: dict[str, Any]
    knowledge_validation: dict[str, Any]
    clarification_needed: bool
    knowledge: dict[str, Any]
    plan: dict[str, Any]
    time_validation: dict[str, Any]
    confidence: float
    scores: dict[str, float]
    score_details: dict[str, list[dict[str, Any]]]
    sql_history: list[dict[str, Any]]
    retry_action: str
    retry_feedback: dict[str, Any]
    validation_errors: list[str]
    sql: str
    rows: list[dict[str, Any]]
    execution_error: str
    retry_count: int
    answer: str
    trace: list[str]
