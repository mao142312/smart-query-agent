from __future__ import annotations

from agent.state import AgentState


TIME_REQUIRED = {"trend_query"}


def validate_intent_for_retrieval(state: AgentState, threshold: float = 0.65) -> AgentState:
    intent = state.get("intent", {})
    targets = [*intent.get("metric_terms", []), *intent.get("actions", []),
               *[x.get("text", "") for x in intent.get("business_objects", [])]]
    target_present = any(str(x).strip() for x in targets)
    blocking = [x for x in intent.get("ambiguities", []) if x.get("blocking")]
    time_sufficient = intent.get("query_type") not in TIME_REQUIRED or bool(intent.get("time_expression"))
    confidence_ok = float(intent.get("confidence", 0)) >= threshold
    checks = [
        {"name": "search_target_present", "passed": target_present, "weight": 0.4},
        {"name": "blocking_ambiguity_absent", "passed": not blocking, "weight": 0.3},
        {"name": "time_sufficient_for_query_type", "passed": time_sufficient, "weight": 0.15},
        {"name": "intent_confidence", "passed": confidence_ok, "weight": 0.15},
    ]
    score = round(sum(x["weight"] for x in checks if x["passed"]), 4)
    retrievable = target_present and not blocking and time_sufficient and confidence_ok
    missing = [] if target_present else ["search_target"]
    if not time_sufficient:
        missing.append("time_expression")
    clarification = None
    if blocking:
        item = blocking[0]
        clarification = f"请明确“{item.get('text', item.get('field', '相关对象'))}”具体指什么。"
    elif missing:
        clarification = "请说明要查询的业务指标或对象。" if "search_target" in missing else "请明确查询时间范围。"
    elif not confidence_ok:
        clarification = ("模型解析不可用，无法可靠识别查询意图。"
                         if intent.get("source") == "raw_question_fallback"
                         else "当前问题的查询意图不够明确，请补充要查询的指标、对象或条件。")
    validation = {"retrievable": retrievable, "score": score, "checks": checks,
                  "missing_fields": missing, "blocking_ambiguities": blocking,
                  "retrieval_hints": [str(x) for x in targets if str(x).strip()],
                  "clarification_question": clarification}
    return {"retrievability_validation": validation,
            "clarification_needed": not retrievable,
            "retry_action": "CONTINUE" if retrievable else "STOP",
            "scores": {**state.get("scores", {}), "intent": score},
            "score_details": {**state.get("score_details", {}), "intent": checks},
            "trace": [*state.get("trace", []), "intent_retrievability_scored"]}
