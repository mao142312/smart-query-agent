from agent.state import AgentState


AGGREGATIONS = {
    "count_distinct": lambda field, _: f"COUNT(DISTINCT {field})",
    "sum": lambda field, config: f"ROUND(SUM({field}), {int(config.get('round', 2))})",
    "count": lambda field, _: f"COUNT({field})",
}


def _literal(value) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _dimension_expression(dimension_id: str, definition: dict, time_column: str) -> str:
    if dimension_id == "date":
        return f"date({time_column})"
    return definition["column"]


def generate_sql(state: AgentState) -> AgentState:
    plan = state["plan"]
    metric = plan["metric"]
    source = metric["source"]
    calculation = metric["calculation"]
    expression = AGGREGATIONS[calculation["aggregation"]](calculation["field"], calculation)
    time_column = source["time_field"]
    clauses = [
        f"{rule['field']} {rule['operator']} {_literal(rule['value'])}"
        for rule in metric.get("required_filters", [])
    ]
    filters = plan["filters"]
    clauses.append(f"date({time_column}) BETWEEN {_literal(filters['start_date'])} AND {_literal(filters['end_date'])}")
    for dimension_id, value in filters.get("dimensions", {}).items():
        definition = plan["dimensions"][dimension_id]
        clauses.append(f"{definition['column']} = {_literal(value)}")
    where = " WHERE " + " AND ".join(clauses)
    group_by = plan.get("group_by", [])
    dimension_columns = [
        (_dimension_expression(item, plan["dimensions"][item], time_column), item)
        for item in group_by
    ]
    dimension_select = ", ".join(f"{expression_sql} AS {alias}" for expression_sql, alias in dimension_columns)
    group_expressions = ", ".join(item[0] for item in dimension_columns)
    wants_total = any(item["kind"] == "total" for item in plan.get("projections", [])) and bool(group_by)
    derivation = next((item.get("derivation") for item in plan.get("projections", []) if item.get("derivation")), None)

    if group_by:
        detail_select = f"{dimension_select}, {expression} AS value"
        detail_sql = f"SELECT {detail_select} FROM {source['table']}{where} GROUP BY {group_expressions}"
        if derivation and derivation["operation"] == "share_of_total":
            sql = (
                "SELECT 'detail' AS row_type, grouped.*, "
                "ROUND(100.0 * value / NULLIF(SUM(value) OVER (), 0), 2) AS derived_value "
                f"FROM ({detail_sql}) AS grouped ORDER BY {', '.join(group_by)}"
            )
        elif wants_total:
            null_dimensions = ", ".join(f"NULL AS {item}" for item in group_by)
            total_sql = f"SELECT 'total' AS row_type, {null_dimensions}, {expression} AS value FROM {source['table']}{where}"
            detail_with_type = f"SELECT 'detail' AS row_type, {detail_select} FROM {source['table']}{where} GROUP BY {group_expressions}"
            sql = f"{total_sql} UNION ALL {detail_with_type} ORDER BY row_type"
        else:
            sql = f"SELECT 'detail' AS row_type, {detail_select} FROM {source['table']}{where} GROUP BY {group_expressions} ORDER BY {', '.join(group_by)}"
    else:
        sql = f"SELECT 'total' AS row_type, {expression} AS value FROM {source['table']}{where}"
    sql += f" LIMIT {int(plan.get('limit', 100))}"
    return {"sql": sql, "validation_errors": [], "trace": [*state.get("trace", []), "sql_generated"]}


def validate_sql(state: AgentState) -> AgentState:
    sql = state.get("sql", "").strip()
    lowered = sql.lower()
    metric = state["plan"]["metric"]
    table = metric["source"]["table"]
    required = metric.get("required_filters", [])
    checks = [
        {"name": "read_only", "passed": lowered.startswith("select ") and ";" not in sql, "weight": 0.25, "message": "仅允许单条 SELECT"},
        {"name": "approved_table", "passed": f" from {table.lower()}" in lowered, "weight": 0.25, "message": "SQL 数据表与知识库不一致"},
        {"name": "required_filters", "passed": all(rule["field"].lower() in lowered and str(rule["value"]).lower() in lowered for rule in required), "weight": 0.25, "message": "缺少知识库规定的强制过滤条件"},
        {"name": "bounded_query", "passed": " limit " in lowered and " between " in lowered, "weight": 0.15, "message": "缺少时间或行数限制"},
        {"name": "metric_expression", "passed": " as value" in lowered, "weight": 0.10, "message": "缺少指标表达式"},
    ]
    score = round(sum(item["weight"] for item in checks if item["passed"]), 4)
    errors = [item["message"] for item in checks if not item["passed"]]
    scores = {**state.get("scores", {}), "sql": score}
    details = {**state.get("score_details", {}), "sql": checks}
    return {
        "scores": scores, "score_details": details, "validation_errors": errors,
        "retry_action": "REGENERATE_SQL" if errors else "CONTINUE",
        "retry_feedback": {"reason_code": "SQL_VALIDATION_FAILED", "issues": errors} if errors else {},
        "trace": [*state.get("trace", []), "sql_scored"]
    }
