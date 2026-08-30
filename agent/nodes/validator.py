from agent.state import AgentState


def _check(name: str, passed: bool, weight: float, message: str = "") -> dict:
    return {"name": name, "passed": passed, "weight": weight, "message": "" if passed else message}


def validate_plan(state: AgentState) -> AgentState:
    plan = state.get("plan", {})
    knowledge = state.get("knowledge", {})
    metric = plan.get("metric")
    candidate_ids = {item.get("metric_id") for item in knowledge.get("metrics", [])}
    matched_once = bool(metric and metric.get("metric_id") in candidate_ids)
    dimensions_valid = bool(metric) and all(
        item in metric.get("supported_dimensions", []) for item in plan.get("group_by", [])
    )
    metric_match_message = "未识别到受支持的指标" if not knowledge.get("metrics") else "匹配到多个指标，请明确指标口径"
    checks = [
        _check("knowledge_unique_match", matched_once, 0.40, metric_match_message),
        _check("metric_definition_complete", bool(metric and metric.get("source") and metric.get("calculation")), 0.30, "指标定义不完整"),
        _check("dimensions_supported", dimensions_valid, 0.30, "指标不支持请求的分析维度"),
    ]
    score = round(sum(item["weight"] for item in checks if item["passed"]), 4)
    errors = [item["message"] for item in checks if not item["passed"]]
    scores = {**state.get("scores", {}), "knowledge": knowledge.get("retrieval_score", 0.0), "plan": score}
    details = {**state.get("score_details", {}), "plan": checks}
    return {
        "confidence": score, "scores": scores, "score_details": details,
        "validation_errors": errors,
        "retry_action": "STOP" if errors else "CONTINUE",
        "trace": [*state.get("trace", []), "plan_scored"]
    }
