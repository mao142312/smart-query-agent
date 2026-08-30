import json
from datetime import date, timedelta


class FakeSemanticLLM:
    """Deterministic model response fixture; production time parsing remains LLM-only."""

    def structured(self, **kwargs):
        payload = json.loads(kwargs["input_text"])
        question = payload["question"]
        if kwargs.get("schema_name") == "query_intent":
            metric_term = next((term for term in ("开户人数", "开户数", "交易金额", "利润") if term in question), question)
            members = [term for term in ("香港", "上海", "北京", "深圳", "广州") if term in question]
            return {
                "query_type": "trend_query" if "趋势" in question or "每天" in question else "metric_query",
                "metric_terms": [metric_term], "business_objects": [], "actions": ["查询"],
                "dimension_terms": ["地区"] if members or "地区" in question else [],
                "member_terms": members, "time_expression": next((x for x in ("最近7天", "昨天", "24年", "3月", "15号") if x in question), None),
                "grouping_terms": ["地区"] if "每个地区" in question or "各地区" in question else [],
                "calculation_intent": "share_of_total" if "占比" in question else None,
                "ambiguities": [], "confidence": 0.9,
            }
        today = date.fromisoformat(payload["reference_date"])
        start = end = today
        expression = None
        detected = False
        resolved = True
        granularity = "day"
        default_applied = True
        error = None
        if "24年13月" in question:
            expression, detected, resolved = "24年13月", True, False
            start = end = None
            granularity, default_applied = None, False
            error = "日期不存在或超出合法范围，请明确查询时间"
        elif "24年" in question:
            expression, detected = "24年", True
            start, end = date(2024, 1, 1), date(2024, 12, 31)
            granularity, default_applied = "year", False
        elif "3月" in question:
            expression, detected = "3月", True
            start, end = date(today.year, 3, 1), date(today.year, 3, 31)
            granularity, default_applied = "month", False
        elif "15号" in question:
            expression, detected = "15号", True
            start = end = date(today.year, today.month, 15)
            default_applied = False
        elif "昨天" in question or "昨日" in question:
            expression, detected = "昨天", True
            start = end = today - timedelta(days=1)
            default_applied = False
        elif "最近7天" in question:
            expression, detected = "最近7天", True
            start, end = today - timedelta(days=7), today - timedelta(days=1)
            default_applied = False
        metrics = payload.get("metrics", [])
        dimensions = payload.get("dimensions", [])
        metric = metrics[0]["metric_id"] if metrics else None
        region = next((item for item in dimensions if item["dimension_id"] == "region"), None)
        dimension_filters = {}
        if region:
            member = next((item for item in region.get("members", []) if item in question), None)
            if member:
                dimension_filters["region"] = member
        group_by = ["date"] if "每天" in question else (["region"] if "每个地区" in question or "各地区" in question else [])
        return {
            "metric_id": metric,
            "group_by": group_by,
            "dimension_filters": dimension_filters,
            "include_total": bool(group_by) and "总" in question,
            "derivation": "share_of_total" if "占比" in question else None,
            "time_detected": detected,
            "time_expression": expression,
            "time_resolved": resolved,
            "start_date": start.isoformat() if start else None,
            "end_date": end.isoformat() if end else None,
            "time_granularity": granularity,
            "default_applied": default_applied,
            "time_error": error,
        }

    def text(self, **kwargs):
        raise RuntimeError("测试模型不负责答案润色")
