from __future__ import annotations

from datetime import date

from agent.state import AgentState


def validate_time_semantics(state: AgentState) -> AgentState:
    plan = state.get("plan", {})
    semantics = plan.get("time_semantics", {})
    filters = plan.get("filters", {})
    start_text = filters.get("start_date")
    end_text = filters.get("end_date")
    error = semantics.get("error") or state.get("llm_error") or "模型未返回可确认的时间范围"
    passed = bool(semantics.get("source") == "llm" and semantics.get("resolved") and start_text and end_text)
    if passed:
        try:
            start = date.fromisoformat(start_text)
            end = date.fromisoformat(end_text)
            passed = start <= end
            if not passed:
                error = "模型返回的开始日期晚于结束日期，请明确查询时间"
        except (TypeError, ValueError):
            passed = False
            error = "模型返回的日期不是合法 ISO 日期，请明确查询时间"
    if not passed and not error.endswith("请明确查询时间"):
        error += "，请明确查询时间"
    check = {
        "name": "time_semantics_resolved",
        "passed": passed,
        "weight": 1.0,
        "message": "" if passed else error,
    }
    validation = {
        "passed": passed,
        "expression": semantics.get("expression"),
        "start_date": start_text,
        "end_date": end_text,
        "granularity": semantics.get("granularity"),
        "source": semantics.get("source"),
        "default_applied": semantics.get("default_applied", False),
        "error": None if passed else error,
    }
    return {
        "time_validation": validation,
        "scores": {**state.get("scores", {}), "time": 1.0 if passed else 0.0},
        "score_details": {**state.get("score_details", {}), "time": [check]},
        "validation_errors": [] if passed else [error],
        "retry_action": "CONTINUE" if passed else "STOP",
        "trace": [*state.get("trace", []), "time_semantics_validated"],
    }
