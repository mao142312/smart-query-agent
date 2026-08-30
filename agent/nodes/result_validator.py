from datetime import date

from agent.state import AgentState


def validate_result(state: AgentState) -> AgentState:
    rows = state.get("rows", [])
    execution_ok = not state.get("execution_error")
    non_empty = bool(rows)
    values_complete = non_empty and all(row.get("value") is not None for row in rows)
    values_valid = values_complete and all(isinstance(row.get("value"), (int, float)) and row["value"] >= 0 for row in rows)
    group_by = state.get("plan", {}).get("group_by", [])
    expected_grouped = bool(group_by)
    grouped_rows = [row for row in rows if row.get("row_type") != "total"]
    dimensions_complete = not expected_grouped or bool(grouped_rows) and all(
        all(row.get(dimension) for dimension in group_by) for row in grouped_rows
    )
    end_date = state.get("plan", {}).get("filters", {}).get("end_date", "")
    freshness_ok = bool(end_date and end_date <= date.today().isoformat())
    checks = [
        {"name": "execution", "passed": execution_ok, "weight": 0.25, "message": state.get("execution_error") or "SQL 执行失败"},
        {"name": "non_empty", "passed": non_empty, "weight": 0.20, "message": "查询结果为空"},
        {"name": "value_completeness", "passed": values_complete, "weight": 0.20, "message": "指标结果包含空值"},
        {"name": "business_range", "passed": values_valid, "weight": 0.15, "message": "指标结果超出合理范围"},
        {"name": "dimension_completeness", "passed": dimensions_complete, "weight": 0.10, "message": "分组维度不完整"},
        {"name": "freshness_window", "passed": freshness_ok, "weight": 0.10, "message": "查询时间超出当前数据窗口"},
    ]
    score = round(sum(item["weight"] for item in checks if item["passed"]), 4)
    issues = [item["message"] for item in checks if not item["passed"]]
    scores = {**state.get("scores", {}), "result": score}
    critical = not execution_ok or not values_complete
    final_score = round(min(scores.get("knowledge", 0), scores.get("time", 0), scores.get("plan", 0), scores.get("sql", 0), score), 4)
    scores["final"] = final_score
    history = [*state.get("sql_history", []), {
        "round": state.get("retry_count", 0) + 1,
        "sql": state.get("sql"), "row_count": len(rows),
        "scores": dict(scores), "issues": issues,
    }]
    retry_action = "RETRY_SQL" if (critical or score < 0.65) else "ANSWER"
    return {
        "scores": scores,
        "score_details": {**state.get("score_details", {}), "result": checks},
        "validation_errors": issues,
        "sql_history": history,
        "retry_action": retry_action,
        "retry_feedback": {"reason_code": "RESULT_VALIDATION_FAILED", "issues": issues} if retry_action == "RETRY_SQL" else {},
        "trace": [*state.get("trace", []), "result_scored"]
    }
