import os
import unittest
from unittest.mock import patch

from pathlib import Path

from agent.graph import build_graph
from smart_ask_data.config import Settings, load_settings
from smart_ask_data.models import AskRequest
from smart_ask_data.service import AskDataService
from tests.fake_semantic_llm import FakeSemanticLLM
from tools.qdrant_client import LocalKnowledgeClient
from tools.trino_client import SQLiteDemoClient


class ServiceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        knowledge = LocalKnowledgeClient(Path(__file__).parents[1] / "data/mock_knowledge.json")
        workflow = build_graph(knowledge, SQLiteDemoClient(), max_retries=2, llm_client=FakeSemanticLLM())
        cls.service = AskDataService(workflow, Settings())

    def test_success_response_hides_debug_fields(self):
        response = self.service.ask(AskRequest("昨天香港开户人数是多少？"))
        self.assertEqual("success", response.status)
        self.assertEqual(1.0, response.confidence)
        self.assertIsNone(response.sql)
        self.assertEqual([], response.trace)

    def test_debug_response_is_traceable(self):
        response = self.service.ask(AskRequest("昨天香港开户人数是多少？", debug=True))
        self.assertIn("FROM account_openings", response.sql)
        self.assertTrue(response.sql_history)
        self.assertIn("result_scored", response.trace)
        self.assertEqual(["intent", "knowledge", "plan", "sql", "result"], [item["id"] for item in response.validation_report])
        intent_step = response.validation_report[0]
        self.assertIn("retrieval_query", intent_step["output"])
        self.assertTrue(intent_step["output"]["metric_terms"])
        result_step = response.validation_report[-1]
        self.assertEqual(6, len(result_step["criteria"]))
        self.assertIn("known_limitations", result_step["output"])

    def test_unknown_metric_is_unreliable(self):
        response = self.service.ask(AskRequest("昨天利润是多少？"))
        self.assertEqual("unreliable", response.status)
        self.assertIn("未识别到受支持的指标", response.answer)

    def test_empty_question_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "不能为空"):
            self.service.ask(AskRequest("  "))

    def test_environment_override(self):
        with patch.dict(os.environ, {"SAD_MAX_RETRIES": "5", "SAD_QUERY_BACKEND": "sqlite",
                                          "SAD_KNOWLEDGE_TOP_N": "7",
                                          "SAD_INTENT_RETRIEVABILITY_THRESHOLD": "0.7"}):
            settings = load_settings()
        self.assertEqual(5, settings.app.max_retries)
        self.assertEqual(7, settings.app.knowledge_top_n)
        self.assertEqual(0.7, settings.app.intent_retrievability_threshold)
        self.assertEqual("sqlite", settings.runtime.query_backend)

    def test_default_model_is_deepseek_v4_flash(self):
        settings = load_settings()
        self.assertEqual("deepseek-v4-flash", settings.llm.model)
        self.assertEqual("https://api.deepseek.com", settings.llm.base_url)
        self.assertEqual("chat_completions", settings.llm.api_mode)
        self.assertEqual("enabled", settings.llm.thinking)


if __name__ == "__main__":
    unittest.main()
