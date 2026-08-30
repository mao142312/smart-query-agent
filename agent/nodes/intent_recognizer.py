from __future__ import annotations

import json
from datetime import date

from agent.state import AgentState


INTENT_SCHEMA = {
    "type": "object",
    "properties": {
        "query_type": {"type": "string"},
        "metric_terms": {"type": "array", "items": {"type": "string"}},
        "business_objects": {"type": "array", "items": {
            "type": "object",
            "properties": {
                "type_hint": {"type": ["string", "null"]},
                "text": {"type": "string"},
            },
            "required": ["type_hint", "text"],
            "additionalProperties": False,
        }},
        "actions": {"type": "array", "items": {"type": "string"}},
        "dimension_terms": {"type": "array", "items": {"type": "string"}},
        "member_terms": {"type": "array", "items": {"type": "string"}},
        "time_expression": {"type": ["string", "null"]},
        "grouping_terms": {"type": "array", "items": {"type": "string"}},
        "calculation_intent": {"type": ["string", "null"]},
        "ambiguities": {"type": "array", "items": {
            "type": "object",
            "properties": {
                "field": {"type": "string"},
                "text": {"type": ["string", "null"]},
                "reason": {"type": ["string", "null"]},
                "blocking": {"type": "boolean"},
            },
            "required": ["field", "text", "reason", "blocking"],
            "additionalProperties": False,
        }},
        "confidence": {"type": "number"},
    },
    "required": ["query_type", "metric_terms", "business_objects", "actions",
                 "dimension_terms", "member_terms", "time_expression", "grouping_terms",
                 "calculation_intent", "ambiguities", "confidence"],
    "additionalProperties": False,
}


def _fallback(question: str, error: str = "") -> dict:
    result = {
        "query_type": "metric_query", "metric_terms": [question],
        "business_objects": [], "actions": [], "dimension_terms": [],
        "member_terms": [], "time_expression": None, "grouping_terms": [],
        "calculation_intent": None, "ambiguities": [], "confidence": 0.45,
        "source": "raw_question_fallback",
    }
    if error:
        result["error"] = error
    return result


def _as_list(value) -> list:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _texts(value) -> list[str]:
    if isinstance(value, dict):
        value = list(value.values())
    result = []
    for item in _as_list(value):
        for nested in _as_list(item):
            text = str(nested).strip()
            if text and text not in result:
                result.append(text)
    return result


def normalize_intent(raw: dict) -> dict:
    """Convert compatible model JSON variants into the workflow intent contract."""
    metrics = _texts(raw.get("metric_terms", raw.get("metric")))
    actions = _texts(raw.get("actions", raw.get("action")))
    dimensions = _texts(raw.get("dimension_terms", raw.get("dimensions")))
    members = _texts(raw.get("member_terms", raw.get("members")))
    grouping = _texts(raw.get("grouping_terms", raw.get("grouping", raw.get("group_by"))))

    objects = []
    object_values = raw.get("business_objects", raw.get("business_object"))
    for item in _as_list(object_values):
        if isinstance(item, dict):
            text = str(item.get("text", "")).strip()
            type_hint = item.get("type_hint")
        else:
            text, type_hint = str(item).strip(), None
        if text and not any(existing["text"] == text for existing in objects):
            objects.append({"type_hint": type_hint, "text": text})

    raw_ambiguities = raw.get("ambiguities", raw.get("ambiguity", []))
    ambiguities = []
    for item in _as_list(raw_ambiguities):
        if not isinstance(item, dict):
            item = {"text": str(item)}
        ambiguities.append({
            "field": str(item.get("field", item.get("type", "intent"))),
            "text": item.get("text"),
            "reason": item.get("reason"),
            "blocking": bool(item.get("blocking", item.get("type") == "blocking")),
        })

    time_value = raw.get("time_expression", raw.get("time"))
    if isinstance(time_value, dict):
        time_value = time_value.get("value") or time_value.get("expression")
    time_expression = str(time_value).strip() if time_value is not None else None

    confidence = raw.get("confidence")
    if confidence is None:
        confidence = 0.35
        confidence += 0.20 if metrics or objects else 0
        confidence += 0.10 if actions else 0
        confidence += 0.10 if time_expression else 0
        confidence += 0.10 if dimensions or members else 0
        confidence += 0.10 if not any(item["blocking"] for item in ambiguities) else 0

    return {
        "query_type": str(raw.get("query_type") or "metric_query"),
        "metric_terms": metrics,
        "business_objects": objects,
        "actions": actions,
        "dimension_terms": dimensions,
        "member_terms": members,
        "time_expression": time_expression,
        "grouping_terms": grouping,
        "calculation_intent": raw.get("calculation_intent", raw.get("calculation")),
        "ambiguities": ambiguities,
        "confidence": round(max(0.0, min(1.0, float(confidence))), 4),
    }


def create_intent_recognizer(llm_client=None):
    def recognize(state: AgentState) -> AgentState:
        request = {"question": state["question"], "reference_date": date.today().isoformat()}
        if llm_client is None:
            intent = _fallback(state["question"])
            return {"intent": intent, "intent_llm_request": request,
                    "intent_llm_response": None,
                    "trace": [*state.get("trace", []), "intent_model_unavailable"]}
        try:
            raw_intent = llm_client.structured(
                instructions=(
                    "你是企业数据查询意图识别器。只提取用户原话中的业务对象、指标说法、"
                    "动作、时间、维度、成员、分组、计算意图和歧义；不得编造正式指标ID、"
                    "数据库表名或字段名。歧义需标明 blocking。严格输出指定 JSON。"
                ), input_text=json.dumps(request, ensure_ascii=False),
                schema_name="query_intent", schema=INTENT_SCHEMA,
            )
            intent = {**normalize_intent(raw_intent), "source": "llm"}
            return {"intent": intent, "intent_llm_request": request,
                    "intent_llm_response": raw_intent,
                    "trace": [*state.get("trace", []), "intent_recognized"]}
        except Exception as exc:
            return {"intent": _fallback(state["question"], str(exc)),
                    "intent_llm_request": request, "intent_llm_response": None,
                    "trace": [*state.get("trace", []), "intent_recognition_failed"]}
    return recognize
