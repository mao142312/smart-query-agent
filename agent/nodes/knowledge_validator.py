from __future__ import annotations

from agent.state import AgentState


def validate_knowledge(state: AgentState, threshold: float = 0.65,
                       ambiguity_margin: float = 0.10) -> AgentState:
    metrics = state.get("knowledge", {}).get("metrics", [])
    top_score = float(metrics[0].get("retrieval_score", 0)) if metrics else 0.0
    complete = bool(metrics) and all(x.get("source") and x.get("calculation") for x in metrics)
    close = len(metrics) > 1 and top_score - float(metrics[1].get("retrieval_score", 0)) < ambiguity_margin
    checks = [
        {"name": "knowledge_candidate_present", "passed": bool(metrics), "weight": 0.4},
        {"name": "knowledge_candidate_score", "passed": top_score >= threshold, "weight": 0.25},
        {"name": "knowledge_candidate_distinct", "passed": not close, "weight": 0.15},
        {"name": "knowledge_definition_complete", "passed": complete, "weight": 0.2},
    ]
    reliable = bool(metrics) and top_score >= threshold and not close and complete
    clarification = None
    if not metrics:
        clarification = "未识别到受支持的指标，请明确要查询的业务指标。"
    elif close:
        names = "、".join(x.get("name", x.get("metric_id", "候选指标")) for x in metrics[:2])
        clarification = f"检索到多个相近指标：{names}。请明确希望采用哪一种口径。"
    elif top_score < threshold:
        clarification = "知识库候选匹配度不足，请补充更具体的业务指标描述。"
    elif not complete:
        clarification = "候选指标定义不完整，暂时无法生成可靠查询。"
    validation = {"reliable": reliable, "score": top_score, "checks": checks,
                  "ambiguous": close, "clarification_question": clarification}
    return {"knowledge_validation": validation,
            "clarification_needed": not reliable,
            "retry_action": "CONTINUE" if reliable else "STOP",
            "scores": {**state.get("scores", {}), "knowledge": top_score},
            "score_details": {**state.get("score_details", {}), "knowledge": checks},
            "trace": [*state.get("trace", []), "knowledge_scored"]}
