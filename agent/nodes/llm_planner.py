from __future__ import annotations

import json
from datetime import date

from agent.state import AgentState


PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "metric_id": {"type": ["string", "null"]},
        "group_by": {"type": "array", "items": {"type": "string"}},
        "dimension_filters": {"type": "object", "additionalProperties": {"type": "string"}},
        "include_total": {"type": "boolean"},
        "derivation": {"type": ["string", "null"]},
        "time_detected": {"type": "boolean"},
        "time_expression": {"type": ["string", "null"]},
        "time_resolved": {"type": "boolean"},
        "start_date": {"type": ["string", "null"]},
        "end_date": {"type": ["string", "null"]},
        "time_granularity": {"type": ["string", "null"]},
        "default_applied": {"type": "boolean"},
        "time_error": {"type": ["string", "null"]},
    },
    "required": [
        "metric_id", "group_by", "dimension_filters", "include_total", "derivation",
        "time_detected", "time_expression", "time_resolved", "start_date", "end_date",
        "time_granularity", "default_applied", "time_error",
    ],
    "additionalProperties": False,
}


def create_semantic_parser(llm_client=None):
    def parse_semantics(state: AgentState) -> AgentState:
        knowledge = state.get("knowledge", {})
        model_input = {
            "question": state["question"],
            "intent": state.get("intent", {}),
            "reference_date": date.today().isoformat(),
            "timezone": knowledge.get("rules", {}).get("timezone", "Asia/Shanghai"),
            "metrics": knowledge.get("metrics", []),
            "dimensions": knowledge.get("dimensions", []),
        }
        if llm_client is None:
            return {
                "llm_used": False,
                "llm_error": "未配置可用的语义解析模型",
                "llm_request": model_input,
                "llm_response": None,
                "trace": [*state.get("trace", []), "llm_semantic_parser_unavailable"],
            }
        try:
            proposal = llm_client.structured(
                instructions=(
                    "你是智能问数规划器。只能选择输入知识库中存在的指标和维度。"
                    "基础指标口径不可修改。derivation 只允许 null 或 share_of_total。"
                    "若用户同时要求总计和分组，include_total=true。"
                    "你必须解析用户问题中的时间语义，并输出明确的 ISO 起止日期。"
                    "两位年份属于当前世纪；只有月份时使用当前年份；只有日期号时使用当前年份和月份。"
                    "用户未提供时间时，可以使用参考日期作为默认日期，但 default_applied=true。"
                    "检测到时间表达但无法无歧义解析时，time_resolved=false，日期填 null，并在 time_error 中提出澄清原因。"
                    "不得把无法解析的时间静默替换为参考日期。"
                    "必须严格输出符合指定字段的 JSON 对象，不要输出 JSON 之外的文字。"
                ),
                input_text=json.dumps(model_input, ensure_ascii=False),
                schema_name="query_plan",
                schema=PLAN_SCHEMA,
            )
            metric_items = knowledge.get("metrics", [])
            dimension_items = knowledge.get("dimensions", [])
            metric_lookup = {
                alias: item for item in metric_items
                for alias in [item["metric_id"], item["name"], *item.get("aliases", [])]
            }
            dimensions = {item["dimension_id"]: item for item in dimension_items}
            dimension_lookup = {
                alias: item["dimension_id"] for item in dimension_items
                for alias in [item["dimension_id"], item["name"], *item.get("aliases", [])]
            }
            metric = metric_lookup.get(proposal.get("metric_id"))
            group_by = [dimension_lookup[item] for item in proposal.get("group_by", []) if item in dimension_lookup]
            allowed = set(metric.get("supported_dimensions", [])) if metric else set()
            group_by = [item for item in group_by if item in allowed]
            dimension_filters = {}
            for raw_key, value in proposal.get("dimension_filters", {}).items():
                key = dimension_lookup.get(raw_key)
                if key and (not dimensions[key].get("members") or value in dimensions[key]["members"]):
                    dimension_filters[key] = value
            plan = dict(state.get("plan", {}))
            plan["filters"] = dict(plan.get("filters", {}))
            plan["metric"] = metric
            plan["group_by"] = group_by
            plan["dimensions"] = dimensions
            plan["filters"]["dimensions"] = dimension_filters
            time_resolved = bool(proposal.get("time_resolved"))
            start_date = proposal.get("start_date") if time_resolved else None
            end_date = proposal.get("end_date") if time_resolved else None
            plan["filters"]["start_date"] = start_date
            plan["filters"]["end_date"] = end_date
            plan["time_semantics"] = {
                "detected": proposal.get("time_detected"),
                "resolved": time_resolved,
                "expression": proposal.get("time_expression"),
                "start_date": start_date,
                "end_date": end_date,
                "granularity": proposal.get("time_granularity"),
                "source": "llm",
                "default_applied": bool(proposal.get("default_applied")),
                "error": proposal.get("time_error") if not time_resolved else None,
            }
            derivation_name = proposal.get("derivation")
            derivation = {"operation": "share_of_total", "label": "占比", "format": "percent"} if derivation_name == "share_of_total" else None
            projections = []
            if proposal.get("include_total") and group_by:
                projections.append({"projection_id": "total", "kind": "total", "group_by": []})
            projections.append({
                "projection_id": "breakdown" if group_by else "total",
                "kind": "breakdown" if group_by else "total",
                "group_by": group_by, "derivation": derivation,
            })
            plan["projections"] = projections
            return {
                "plan": plan,
                "llm_used": True,
                "llm_error": "",
                "llm_request": model_input,
                "llm_response": proposal,
                "trace": [*state.get("trace", []), "llm_semantics_parsed"],
            }
        except Exception as exc:
            return {
                "llm_used": False,
                "llm_error": str(exc),
                "llm_request": model_input,
                "llm_response": None,
                "trace": [*state.get("trace", []), "llm_semantic_parser_failed"],
            }

    return parse_semantics


# Backward-compatible alias for callers outside the graph module.
create_planner = create_semantic_parser
