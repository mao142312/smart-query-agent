from __future__ import annotations

import logging
import uuid

from smart_ask_data.config import Settings
from smart_ask_data.models import AskRequest, AskResponse
from smart_ask_data.trace_store import create_question_trace, write_failure, write_summary


logger = logging.getLogger(__name__)


CHECK_LABELS = {
    "knowledge_unique_match": ("指标唯一匹配", "知识检索应只命中一个明确指标，避免口径歧义。"),
    "metric_definition_complete": ("指标定义完整", "指标必须包含来源表、计算公式和强制过滤条件。"),
    "time_semantics_resolved": ("时间语义已确认", "原始时间表达必须被明确解析为一致的开始和结束日期，禁止静默回退。"),
    "dimensions_supported": ("维度受到支持", "所有分组维度必须在指标知识定义的允许范围内。"),
    "read_only": ("只读安全", "SQL 必须为单条 SELECT，不能包含写入或结构变更。"),
    "approved_table": ("数据源白名单", "SQL 只能访问知识库为该指标指定的数据表。"),
    "required_filters": ("强制条件完整", "SQL 必须包含知识库定义的全部业务过滤条件。"),
    "bounded_query": ("查询范围受限", "SQL 必须包含时间范围及返回行数限制。"),
    "metric_expression": ("指标表达式存在", "SQL 必须输出统一的 value 指标列。"),
    "execution": ("执行成功", "查询引擎必须成功完成 SQL，不得超时或报错。"),
    "non_empty": ("结果非空", "查询至少返回一行数据；空结果不能作为可靠指标输出。"),
    "value_completeness": ("指标值完整", "每一行的指标值都必须非空。"),
    "business_range": ("基础业务范围", "当前基础规则要求指标是非负数；后续应由知识库提供指标专属上下界。"),
    "dimension_completeness": ("分组维度完整", "明细行必须包含计划要求的全部分组维度。"),
    "freshness_window": ("查询日期有效", "当前仅确认查询结束日期不晚于今天；尚未校验真实数据分区更新时间。"),
}


def _criteria(checks: list[dict]) -> list[dict]:
    result = []
    for check in checks:
        label, basis = CHECK_LABELS.get(check["name"], (check["name"], check.get("message", "")))
        result.append({
            "id": check["name"], "label": label, "basis": basis,
            "passed": check["passed"], "weight": check["weight"],
            "earned": check["weight"] if check["passed"] else 0,
            "issue": "" if check["passed"] else check.get("message", "未通过"),
        })
    return result


def _build_validation_report(result: dict) -> list[dict]:
    knowledge = result.get("knowledge", {})
    plan = result.get("plan", {})
    metric = plan.get("metric") or {}
    dimensions = plan.get("dimensions", {})
    scores = result.get("scores", {})
    details = result.get("score_details", {})
    matched_metrics = [item.get("name") for item in knowledge.get("metrics", [])]
    group_names = [dimensions.get(item, {}).get("name", item) for item in plan.get("group_by", [])]
    projections = [
        {
            "type": item.get("kind"), "group_by": item.get("group_by", []),
            "derivation": (item.get("derivation") or {}).get("label"),
        }
        for item in plan.get("projections", [])
    ]
    rows = result.get("rows", [])
    null_values = sum(1 for row in rows if row.get("value") is None)
    negative_values = sum(1 for row in rows if isinstance(row.get("value"), (int, float)) and row["value"] < 0)
    intent = result.get("intent", {})
    retrieval_query = result.get("retrieval_query", {})
    retrievability = result.get("retrievability_validation", {})
    return [
        {
            "id": "intent", "title": "意图与可检索性", "score": retrievability.get("score", 0),
            "status": "passed" if retrievability.get("retrievable") else "warning",
            "summary": "已形成结构化知识检索条件" if retrievability.get("retrievable") else "需要补充查询意图",
            "output": {
                "query_type": intent.get("query_type"),
                "metric_terms": intent.get("metric_terms", []),
                "business_objects": intent.get("business_objects", []),
                "time_expression": intent.get("time_expression"),
                "ambiguities": intent.get("ambiguities", []),
                "retrieval_query": retrieval_query,
            },
            "criteria": retrievability.get("checks", []),
        },
        {
            "id": "knowledge", "title": "知识检索", "score": scores.get("knowledge", 0),
            "status": "passed" if scores.get("knowledge", 0) >= 0.65 else "warning",
            "summary": f"命中指标：{'、'.join(matched_metrics) if matched_metrics else '无'}；来源：{knowledge.get('source', '未知')}。",
            "output": {
                "matched_metrics": matched_metrics,
                "matched_dimensions": [item.get("name") for item in knowledge.get("dimensions", [])],
                "knowledge_version": knowledge.get("knowledge_version"),
                "retrieval_score": knowledge.get("retrieval_score", 0),
            },
            "criteria": [],
        },
        {
            "id": "plan", "title": "语义规划", "score": min(scores.get("time", 0), scores.get("plan", 0)),
            "status": "passed" if not any(not item["passed"] for item in [*details.get("time", []), *details.get("plan", [])]) else "warning",
            "summary": f"指标：{metric.get('name', '未识别')}；分组：{'、'.join(group_names) if group_names else '无'}。",
            "output": {
                "metric_id": metric.get("metric_id"), "metric_name": metric.get("name"),
                "time_range": [plan.get("filters", {}).get("start_date"), plan.get("filters", {}).get("end_date")],
                "time_semantics": plan.get("time_semantics", {}),
                "dimension_filters": plan.get("filters", {}).get("dimensions", {}),
                "group_by": group_names, "projections": projections,
                "llm_request": result.get("llm_request"),
                "llm_response": result.get("llm_response"),
                "time_validation": result.get("time_validation"),
                "planned_by_llm": "llm_semantics_parsed" in result.get("trace", []),
            },
            "criteria": _criteria([*details.get("time", []), *details.get("plan", [])]),
        },
        {
            "id": "sql", "title": "SQL 校验", "score": scores.get("sql", 0),
            "status": "passed" if scores.get("sql", 0) >= 0.65 else "warning",
            "summary": f"SQL 校验得分 {scores.get('sql', 0):.0%}，共检查 {len(details.get('sql', []))} 项规则。",
            "output": {"sql": result.get("sql"), "table": metric.get("source", {}).get("table")},
            "criteria": _criteria(details.get("sql", [])),
        },
        {
            "id": "result", "title": "结果评分", "score": scores.get("result", 0),
            "status": "passed" if scores.get("result", 0) >= 0.65 else "warning",
            "summary": f"返回 {len(rows)} 行；空指标值 {null_values} 个；负值 {negative_values} 个。",
            "output": {
                "row_count": len(rows), "null_value_count": null_values,
                "negative_value_count": negative_values,
                "execution_error": result.get("execution_error") or None,
                "scoring_method": "各检查项通过即获得对应权重，总分为权重之和。",
                "known_limitations": ["尚未接入真实数据分区新鲜度", "尚未接入历史波动基线和权威报表对账"],
            },
            "criteria": _criteria(details.get("result", [])),
        },
    ]


class AskDataService:
    def __init__(self, workflow, settings: Settings):
        self.workflow = workflow
        self.settings = settings

    def ask(self, request: AskRequest) -> AskResponse:
        request.validate()
        request_id = str(uuid.uuid4())
        question = request.question.strip()
        trace_dir = create_question_trace(question, request_id)
        try:
            result = self.workflow.invoke({
                "question": question, "request_id": request_id,
                "trace_log_dir": str(trace_dir),
                "retry_count": 0, "trace": [], "scores": {},
                "score_details": {}, "sql_history": [],
            })
        except Exception as exc:
            write_failure(trace_dir, request_id, question, exc)
            raise
        confidence = result.get("scores", {}).get("final", 0.0)
        reliable = confidence >= self.settings.app.confidence_threshold and result.get("retry_action") not in {"STOP", "FAILED"}
        status = "success" if reliable else "unreliable"
        write_summary(trace_dir, result, status)
        logger.info("ask completed", extra={"request_id": request_id, "status": status, "confidence": confidence})
        return AskResponse(
            request_id=request_id, answer=result["answer"], confidence=confidence,
            status=status, sql=result.get("sql") if request.debug else None,
            scores=result.get("scores", {}),
            score_details=result.get("score_details", {}) if request.debug else {},
            sql_history=result.get("sql_history", []) if request.debug else [],
            trace=result.get("trace", []) if request.debug else [],
            llm_used=result.get("llm_used", False),
            llm_error=result.get("llm_error") if request.debug else None,
            validation_report=_build_validation_report(result),
        )
