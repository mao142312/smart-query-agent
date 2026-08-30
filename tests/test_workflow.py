import unittest
import os
from datetime import date
from unittest.mock import patch

from main import ask
from agent.graph import build_graph
from tools.qdrant_client import LocalKnowledgeClient
from tools.trino_client import SQLiteDemoClient
from pathlib import Path
from tests.fake_semantic_llm import FakeSemanticLLM


class WorkflowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        knowledge = LocalKnowledgeClient(Path(__file__).parents[1] / "data/mock_knowledge.json")
        cls.app = build_graph(knowledge, SQLiteDemoClient(), max_retries=2, llm_client=FakeSemanticLLM())

    def test_yesterday_region_metric(self):
        answer = ask(self.app, "昨天香港开户人数是多少？")
        self.assertIn("香港", answer)
        self.assertIn("开户人数", answer)
        self.assertNotIn("无法可靠回答", answer)
        self.assertIn("可信度：100%", answer)

    def test_workflow_recognizes_intent_before_retrieval(self):
        result = self.app.invoke({"question": "昨天香港开户人数是多少？", "retry_count": 0, "trace": []})
        expected = ["intent_recognized", "intent_retrievability_scored",
                    "retrieval_query_built", "rag_retrieved", "knowledge_scored"]
        self.assertEqual(expected, [item for item in result["trace"] if item in expected])
        self.assertIsInstance(result["knowledge"]["retrieval_query"], dict)

    def test_daily_trend(self):
        answer = ask(self.app, "最近7天每天的开户人数")
        self.assertIn("开户人数", answer)
        self.assertIn("为", answer)

    def test_two_digit_year_uses_current_century(self):
        result = self.app.invoke({"question": "24年香港开户人数是多少？", "retry_count": 0, "trace": []})
        self.assertEqual("2024-01-01", result["plan"]["filters"]["start_date"])
        self.assertEqual("2024-12-31", result["plan"]["filters"]["end_date"])
        self.assertEqual("24年", result["plan"]["time_semantics"]["expression"])
        self.assertFalse(result["plan"]["time_semantics"]["default_applied"])
        self.assertIn("BETWEEN '2024-01-01' AND '2024-12-31'", result["sql"])
        self.assertIn("24年", result["answer"])
        self.assertIn("2024-01-01 至 2024-12-31", result["answer"])

    def test_missing_time_uses_disclosed_default(self):
        result = self.app.invoke({"question": "香港开户人数是多少？", "retry_count": 0, "trace": []})
        self.assertTrue(result["plan"]["time_semantics"]["default_applied"])
        self.assertIn("用户未指定时间，按默认日期", result["answer"])

    def test_month_only_uses_current_year(self):
        result = self.app.invoke({"question": "3月香港开户人数是多少？", "retry_count": 0, "trace": []})
        year = date.today().year
        self.assertEqual(f"{year}-03-01", result["plan"]["filters"]["start_date"])
        self.assertEqual(f"{year}-03-31", result["plan"]["filters"]["end_date"])

    def test_day_only_uses_current_month(self):
        result = self.app.invoke({"question": "15号香港开户人数是多少？", "retry_count": 0, "trace": []})
        expected = date(date.today().year, date.today().month, 15).isoformat()
        self.assertEqual(expected, result["plan"]["filters"]["start_date"])
        self.assertEqual(expected, result["plan"]["filters"]["end_date"])

    def test_unresolved_time_stops_before_sql(self):
        result = self.app.invoke({"question": "24年13月香港开户人数是多少？", "retry_count": 0, "trace": []})
        self.assertEqual("STOP", result["retry_action"])
        self.assertNotIn("sql", result)
        self.assertIn("请明确查询时间", result["answer"])
        check = next(item for item in result["score_details"]["time"] if item["name"] == "time_semantics_resolved")
        self.assertFalse(check["passed"])

    def test_missing_time_model_stops_before_sql(self):
        knowledge = LocalKnowledgeClient(Path(__file__).parents[1] / "data/mock_knowledge.json")
        app = build_graph(knowledge, SQLiteDemoClient(), max_retries=2, llm_client=None)
        result = app.invoke({"question": "24年香港开户人数是多少？", "retry_count": 0, "trace": []})
        self.assertEqual("STOP", result["retry_action"])
        self.assertNotIn("sql", result)
        self.assertIn("模型解析", result["answer"])

    def test_passed_plan_checks_do_not_keep_failure_messages(self):
        result = self.app.invoke({"question": "昨天香港开户人数是多少？", "retry_count": 0, "trace": []})
        self.assertTrue(all(not item["message"] for item in result["score_details"]["plan"] if item["passed"]))

    def test_unknown_metric(self):
        answer = ask(self.app, "昨天的利润是多少？")
        self.assertIn("未识别到受支持的指标", answer)

    def test_every_sql_round_is_scored(self):
        result = self.app.invoke({"question": "昨天香港开户人数是多少？", "retry_count": 0, "trace": []})
        self.assertEqual(1, len(result["sql_history"]))
        self.assertEqual(1.0, result["sql_history"][0]["scores"]["sql"])
        self.assertEqual(1.0, result["sql_history"][0]["scores"]["result"])

    def test_sql_comes_from_knowledge_definition(self):
        result = self.app.invoke({"question": "昨天上海的交易金额是多少？", "retry_count": 0, "trace": []})
        self.assertIn("ROUND(SUM(amount), 2)", result["sql"])
        self.assertIn("FROM transactions", result["sql"])
        self.assertIn("status = 'SUCCESS'", result["sql"])

    def test_low_score_result_retries_with_limit(self):
        class EmptyQueryClient:
            def execute(self, sql):
                return []

        knowledge = LocalKnowledgeClient(Path(__file__).parents[1] / "data/mock_knowledge.json")
        app = build_graph(knowledge, EmptyQueryClient(), max_retries=2, llm_client=FakeSemanticLLM())
        result = app.invoke({"question": "昨天香港开户人数是多少？", "retry_count": 0, "trace": []})
        self.assertEqual(3, len(result["sql_history"]))
        self.assertEqual("FAILED", result["retry_action"])
        self.assertIn("查询结果为空", result["answer"])

    def test_total_and_region_breakdown_are_both_answered(self):
        result = self.app.invoke({"question": "总的开户数是多少？然后每个地区的开户数是多少？", "retry_count": 0, "trace": []})
        self.assertIn("开户人数总计", result["answer"])
        self.assertIn("按地区明细", result["answer"])
        self.assertIn("香港", result["answer"])
        self.assertIn("上海", result["answer"])
        self.assertIn("北京", result["answer"])
        self.assertEqual(4, len(result["rows"]))

    def test_derived_share_uses_base_metric(self):
        result = self.app.invoke({"question": "各地区开户人数和占比分别是多少？", "retry_count": 0, "trace": []})
        self.assertIn("占比", result["answer"])
        self.assertTrue(all("derived_value" in row for row in result["rows"]))
        self.assertAlmostEqual(100.0, sum(row["derived_value"] for row in result["rows"]), places=1)

    def test_real_llm_adapter_contract_is_used(self):
        class FakeLLM:
            structured_calls = 0
            text_calls = 0

            def structured(self, **kwargs):
                self.structured_calls += 1
                if kwargs.get("schema_name") == "query_intent":
                    return {
                        "query_type": "metric_query", "metric_terms": ["开户数"],
                        "business_objects": [], "actions": ["查询"],
                        "dimension_terms": ["地区"], "member_terms": [],
                        "time_expression": None, "grouping_terms": ["地区"],
                        "calculation_intent": None, "ambiguities": [], "confidence": 0.9,
                    }
                return {
                    "metric_id": "account_open_user_count", "group_by": ["region"],
                    "dimension_filters": {}, "include_total": True, "derivation": None,
                    "time_detected": False, "time_expression": None, "time_resolved": True,
                    "start_date": date.today().isoformat(), "end_date": date.today().isoformat(),
                    "time_granularity": "day", "default_applied": True, "time_error": None,
                }

            def text(self, **kwargs):
                self.text_calls += 1
                return "开户人数总计为9；上海为3，北京为4，香港为2。"

        fake = FakeLLM()
        knowledge = LocalKnowledgeClient(Path(__file__).parents[1] / "data/mock_knowledge.json")
        from tools.trino_client import SQLiteDemoClient
        app = build_graph(knowledge, SQLiteDemoClient(), max_retries=2, llm_client=fake)
        result = app.invoke({"question": "总开户数和各地区分别是多少？", "retry_count": 0, "trace": []})
        self.assertEqual(2, fake.structured_calls)
        self.assertEqual(1, fake.text_calls)
        self.assertTrue(result["llm_used"])
        self.assertIn("llm_semantics_parsed", result["trace"])


if __name__ == "__main__":
    unittest.main()
