from __future__ import annotations

from agent.state import AgentState


def _unresolved_time() -> dict:
    return {
        "detected": None,
        "resolved": False,
        "expression": None,
        "start_date": None,
        "end_date": None,
        "granularity": None,
        "source": "model_required",
        "default_applied": False,
        "error": "时间语义尚未经过模型解析，无法安全生成查询",
    }


def _is_grouping(question: str, dimension: dict) -> bool:
    terms = [dimension["name"], *dimension.get("aliases", [])]
    prefixes = ("每个", "各", "按", "分")
    return any(f"{prefix}{term}" in question for prefix in prefixes for term in terms) or (
        dimension["dimension_id"] == "date" and "趋势" in question
    )


def _dimension_filters(question: str, dimensions: list[dict]) -> dict[str, str]:
    filters = {}
    for dimension in dimensions:
        value = next((item for item in dimension.get("members", []) if item in question), None)
        if value:
            filters[dimension["dimension_id"]] = value
    return filters


def plan(state: AgentState) -> AgentState:
    knowledge = state.get("knowledge", {})
    metrics = knowledge.get("metrics", [])
    metric = metrics[0] if metrics else None
    dimensions = knowledge.get("dimensions", [])
    time_semantics = _unresolved_time()
    group_by = [item["dimension_id"] for item in dimensions if _is_grouping(state["question"], item)]
    wants_total = bool(group_by) and any(term in state["question"] for term in ("总", "全部", "整体"))
    derivation = None
    if any(term in state["question"] for term in ("占比", "比例", "百分比")):
        derivation = {"operation": "share_of_total", "label": "占比", "format": "percent"}
    projections = []
    if wants_total:
        projections.append({"projection_id": "total", "kind": "total", "group_by": []})
    projections.append({
        "projection_id": "breakdown" if group_by else "total",
        "kind": "breakdown" if group_by else "total",
        "group_by": group_by,
        "derivation": derivation,
    })
    result = {
        "metric": metric,
        "filters": {
            "start_date": time_semantics["start_date"],
            "end_date": time_semantics["end_date"],
            "dimensions": _dimension_filters(state["question"], dimensions),
        },
        "time_semantics": time_semantics,
        "group_by": group_by,
        "projections": projections,
        "dimensions": {item["dimension_id"]: item for item in dimensions},
        "limit": knowledge.get("rules", {}).get("default_limit", 100),
        "knowledge_version": knowledge.get("knowledge_version"),
    }
    return {"plan": result, "trace": [*state.get("trace", []), "planned"]}
