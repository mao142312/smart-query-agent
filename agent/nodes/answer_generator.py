import json
import re

from agent.state import AgentState


def _format_value(value, derivation: dict | None = None) -> str:
    if derivation and derivation.get("format") == "percent":
        return f"{value}%"
    return str(value)


def _dimension_text(row: dict, group_by: list[str], dimensions: dict) -> str:
    return "、".join(f"{dimensions[item]['name']}“{row[item]}”" for item in group_by)


def _filter_scope(plan: dict) -> str:
    filters = plan.get("filters", {}).get("dimensions", {})
    dimensions = plan.get("dimensions", {})
    return "、".join(f"{dimensions[key]['name']}“{value}”" for key, value in filters.items())


def _time_scope_text(plan: dict) -> str:
    semantics = plan.get("time_semantics", {})
    start = semantics.get("start_date") or plan.get("filters", {}).get("start_date")
    end = semantics.get("end_date") or plan.get("filters", {}).get("end_date")
    if not start or not end:
        return ""
    scope = start if start == end else f"{start} 至 {end}"
    if semantics.get("default_applied"):
        return f"用户未指定时间，按默认日期 {scope} 查询。"
    expression = semantics.get("expression")
    return f"时间表达“{expression}”已解析为 {scope}。" if expression else f"查询时间：{scope}。"


def _render_result(plan: dict, rows: list[dict]) -> str:
    metric_name = plan["metric"]["name"]
    group_by = plan.get("group_by", [])
    dimensions = plan.get("dimensions", {})
    total_rows = [row for row in rows if row.get("row_type") == "total"]
    detail_rows = [row for row in rows if row.get("row_type") == "detail"]
    parts = []
    if total_rows:
        scope = _filter_scope(plan)
        subject = f"{scope}的{metric_name}" if scope else f"{metric_name}总计"
        parts.append(f"{subject}为 {total_rows[0]['value']}。")
    if detail_rows:
        derivation = next((item.get("derivation") for item in plan.get("projections", []) if item.get("derivation")), None)
        detail_parts = []
        for row in detail_rows:
            text = f"{_dimension_text(row, group_by, dimensions)}：{metric_name}为 {row['value']}"
            if derivation and row.get("derived_value") is not None:
                text += f"，{derivation['label']}为 {_format_value(row['derived_value'], derivation)}"
            detail_parts.append(text)
        dimension_names = "、".join(dimensions[item]["name"] for item in group_by)
        parts.append(f"按{dimension_names}明细：" + "；".join(detail_parts) + "。")
    return "\n".join(parts)


def _audit_text(state: AgentState) -> str:
    scores = state.get("scores", {})
    plan = state["plan"]
    return (
        f"可信度：{scores.get('final', 0):.0%}；"
        f"知识库版本：{plan.get('knowledge_version', 'unknown')}；"
        f"数据来源：{plan['metric']['source']['table']}；"
        f"SQL 校验：{scores.get('sql', 0):.0%}；结果校验：{scores.get('result', 0):.0%}。"
    )


def _model_answer_is_grounded(answer: str, rows: list[dict]) -> bool:
    expected = {str(value) for row in rows for key, value in row.items() if key in {"value", "derived_value"} and value is not None}
    if not all(value in answer for value in expected):
        return False
    numeric_tokens = set(re.findall(r"\d+(?:\.\d+)?", answer))
    allowed_tokens = {token for value in expected for token in re.findall(r"\d+(?:\.\d+)?", value)}
    return numeric_tokens.issubset(allowed_tokens)


def _generate_answer(state: AgentState, llm_client=None) -> AgentState:
    scores = state.get("scores", {})
    errors = state.get("validation_errors", [])
    llm_used = state.get("llm_used", False)
    llm_error = state.get("llm_error", "")
    clarification = (
        state.get("retrievability_validation", {}).get("clarification_question")
        or state.get("knowledge_validation", {}).get("clarification_question")
    )
    if clarification:
        answer = clarification
    elif state.get("retry_action") in {"STOP", "FAILED"} or scores.get("final", 1) < 0.65:
        answer = "暂时无法可靠回答：" + "；".join(errors or ["综合可信度未达到输出阈值"])
    else:
        plan = state["plan"]
        rows = state.get("rows", [])
        deterministic = _render_result(plan, rows)
        answer = deterministic
        if llm_client is not None:
            try:
                candidate = llm_client.text(
                    instructions=(
                        "你是数据分析回答生成器。只根据给定查询结果回答，不得推测、补充或修改任何数值。"
                        "必须完整回答所有总计、分组和衍生指标，使用简洁中文，不输出可信度或 SQL。"
                    ),
                    input_text=json.dumps({"question": state["question"], "plan": plan, "rows": rows}, ensure_ascii=False, default=str),
                )
                if _model_answer_is_grounded(candidate, rows):
                    answer = candidate
                    llm_used = True
                else:
                    llm_error = "模型回答未通过数值忠实性校验"
            except Exception as exc:
                llm_error = str(exc)
        time_scope = _time_scope_text(plan)
        if time_scope:
            answer = time_scope + "\n" + answer
        answer += "\n" + _audit_text(state)
    return {
        "answer": answer, "llm_used": llm_used, "llm_error": llm_error,
        "trace": [*state.get("trace", []), "answer_generated"]
    }


def generate_answer(state: AgentState) -> AgentState:
    return _generate_answer(state)


def create_answer_generator(llm_client=None):
    def answer(state: AgentState) -> AgentState:
        return _generate_answer(state, llm_client)
    return answer
