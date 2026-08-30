import json
import tempfile
import unittest
from pathlib import Path

from agent.nodes.intent_recognizer import create_intent_recognizer
from agent.nodes.knowledge_validator import validate_knowledge
from agent.nodes.llm_planner import create_semantic_parser
from agent.nodes.retrievability_validator import validate_intent_for_retrieval
from agent.nodes.retrieval_query_builder import build_retrieval_query
from tools.qdrant_client import LocalKnowledgeClient


class IntentFixtureLLM:
    def structured(self, **kwargs):
        return {
            "query_type": "metric_query",
            "metric_terms": ["业绩"],
            "business_objects": [{"type_hint": "employee", "text": "齐鑫涛"}],
            "actions": ["查询"],
            "dimension_terms": ["员工"],
            "member_terms": ["齐鑫涛"],
            "time_expression": "最近一个月",
            "grouping_terms": [],
            "calculation_intent": None,
            "ambiguities": [{"field": "metric", "text": "业绩", "blocking": False}],
            "confidence": 0.82,
        }


class IntentWorkflowTest(unittest.TestCase):
    def test_legacy_intent_shape_is_normalized_before_retrievability_validation(self):
        class LegacyShapeLLM:
            def structured(self, **kwargs):
                return {
                    "business_object": "开户",
                    "metric": "开户数量",
                    "action": "查询",
                    "time": "2026年8月",
                    "dimensions": ["业务员"],
                    "members": {"业务员": "齐鑫涛"},
                    "grouping": None,
                    "calculation_intent": "count",
                    "ambiguity": [],
                }

        recognized = create_intent_recognizer(LegacyShapeLLM())({
            "question": "查询业务员齐鑫涛8月份的开户数量", "trace": [],
        })
        intent = recognized["intent"]

        self.assertEqual(["开户数量"], intent["metric_terms"])
        self.assertEqual([{"type_hint": None, "text": "开户"}], intent["business_objects"])
        self.assertEqual(["查询"], intent["actions"])
        self.assertEqual("2026年8月", intent["time_expression"])
        self.assertEqual(["业务员"], intent["dimension_terms"])
        self.assertEqual(["齐鑫涛"], intent["member_terms"])
        self.assertGreaterEqual(intent["confidence"], 0.65)

        validated = validate_intent_for_retrieval(recognized, threshold=0.65)
        self.assertTrue(validated["retrievability_validation"]["retrievable"])
        self.assertEqual("CONTINUE", validated["retry_action"])

    def test_intent_recognizer_extracts_search_clues(self):
        node = create_intent_recognizer(IntentFixtureLLM())
        result = node({"question": "查询齐鑫涛最近一个月业绩", "trace": []})
        self.assertEqual(["业绩"], result["intent"]["metric_terms"])
        self.assertEqual("齐鑫涛", result["intent"]["business_objects"][0]["text"])
        self.assertEqual("最近一个月", result["intent"]["time_expression"])
        self.assertIn("intent_recognized", result["trace"])

    def test_metric_term_is_searchable_when_business_term_is_nonblocking(self):
        intent = IntentFixtureLLM().structured()
        result = validate_intent_for_retrieval({"intent": intent, "trace": []}, threshold=0.65)
        self.assertTrue(result["retrievability_validation"]["retrievable"])
        self.assertEqual("CONTINUE", result["retry_action"])

    def test_unresolved_reference_stops_before_retrieval(self):
        intent = IntentFixtureLLM().structured()
        intent["ambiguities"] = [
            {"field": "business_object", "text": "他", "blocking": True,
             "reason": "缺少可解析的指代对象"}
        ]
        result = validate_intent_for_retrieval({"intent": intent, "trace": []}, threshold=0.65)
        self.assertFalse(result["retrievability_validation"]["retrievable"])
        self.assertTrue(result["clarification_needed"])
        self.assertEqual("STOP", result["retry_action"])
        self.assertIn("他", result["retrievability_validation"]["clarification_question"])

    def test_retrieval_query_is_built_from_intent_clues(self):
        intent = IntentFixtureLLM().structured()
        result = build_retrieval_query({
            "question": "查询齐鑫涛最近一个月业绩", "intent": intent, "trace": []
        }, top_n=5)
        query = result["retrieval_query"]
        self.assertEqual(["业绩"], query["metric_terms"])
        self.assertEqual(["齐鑫涛"], query["member_terms"])
        self.assertEqual(5, query["top_n"])

    def test_structured_knowledge_search_returns_ranked_top_n(self):
        data = {
            "version": "test", "dimensions": [], "tables": [], "rules": {},
            "metrics": [
                {"metric_id": "m1", "name": "员工综合业绩", "aliases": ["业绩"],
                 "description": "员工综合考核业绩", "source": {"table": "t1"}},
                {"metric_id": "m2", "name": "员工业绩金额", "aliases": ["业绩金额"],
                 "description": "员工产生的金额业绩", "source": {"table": "t2"}},
                {"metric_id": "m3", "name": "团队业绩", "aliases": [],
                 "description": "团队业绩汇总", "source": {"table": "t3"}},
            ],
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "knowledge.json"
            path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            result = LocalKnowledgeClient(path).search({
                "original_question": "查询员工业绩", "query_texts": ["员工业绩"],
                "metric_terms": ["业绩"], "business_object_terms": ["员工"],
                "action_terms": ["查询"], "dimension_terms": [], "member_terms": [],
                "top_n": 2,
            })
        self.assertEqual(2, len(result["metrics"]))
        self.assertGreaterEqual(result["metrics"][0]["retrieval_score"], result["metrics"][1]["retrieval_score"])

    def test_empty_knowledge_stops_before_planning(self):
        result = validate_knowledge({"knowledge": {"metrics": []}, "trace": []},
                                    threshold=0.65, ambiguity_margin=0.10)
        self.assertEqual("STOP", result["retry_action"])
        self.assertTrue(result["clarification_needed"])

    def test_close_knowledge_candidates_request_clarification(self):
        knowledge = {"metrics": [
            {"metric_id": "m1", "name": "综合业绩", "retrieval_score": 0.90,
             "source": {"table": "t1"}, "calculation": {"aggregation": "sum"}},
            {"metric_id": "m2", "name": "成交业绩", "retrieval_score": 0.85,
             "source": {"table": "t2"}, "calculation": {"aggregation": "sum"}},
        ]}
        result = validate_knowledge({"knowledge": knowledge, "trace": []},
                                    threshold=0.65, ambiguity_margin=0.10)
        self.assertEqual("STOP", result["retry_action"])
        self.assertIn("综合业绩", result["knowledge_validation"]["clarification_question"])
        self.assertIn("成交业绩", result["knowledge_validation"]["clarification_question"])

    def test_grounded_planner_receives_intent_and_candidates(self):
        class RecordingPlanLLM:
            payload = None
            def structured(self, **kwargs):
                self.payload = json.loads(kwargs["input_text"])
                return {
                    "metric_id": "m1", "group_by": [], "dimension_filters": {},
                    "include_total": False, "derivation": None,
                    "time_detected": True, "time_expression": "昨天", "time_resolved": True,
                    "start_date": "2026-08-29", "end_date": "2026-08-29",
                    "time_granularity": "day", "default_applied": False, "time_error": None,
                }
        llm = RecordingPlanLLM()
        state = {
            "question": "昨天业绩", "intent": {"metric_terms": ["业绩"]},
            "knowledge": {"metrics": [{"metric_id": "m1", "name": "综合业绩",
                "aliases": [], "supported_dimensions": [], "source": {"table": "t"},
                "calculation": {"aggregation": "sum", "field": "value"}}],
                "dimensions": [], "rules": {}},
            "plan": {"filters": {}, "projections": []}, "trace": [],
        }
        result = create_semantic_parser(llm)(state)
        self.assertEqual(state["intent"], llm.payload["intent"])
        self.assertEqual("m1", result["plan"]["metric"]["metric_id"])

    def test_grounded_planner_rejects_metric_outside_candidates(self):
        class InvalidMetricLLM:
            def structured(self, **kwargs):
                return {
                    "metric_id": "invented_metric", "group_by": [], "dimension_filters": {},
                    "include_total": False, "derivation": None,
                    "time_detected": True, "time_expression": "昨天", "time_resolved": True,
                    "start_date": "2026-08-29", "end_date": "2026-08-29",
                    "time_granularity": "day", "default_applied": False, "time_error": None,
                }
        state = {
            "question": "昨天业绩", "intent": {"metric_terms": ["业绩"]},
            "knowledge": {"metrics": [{"metric_id": "m1", "name": "综合业绩",
                "aliases": [], "supported_dimensions": [], "source": {"table": "t"},
                "calculation": {"aggregation": "sum", "field": "value"}}],
                "dimensions": [], "rules": {}},
            "plan": {"filters": {}, "projections": []}, "trace": [],
        }
        result = create_semantic_parser(InvalidMetricLLM())(state)
        self.assertIsNone(result["plan"]["metric"])


if __name__ == "__main__":
    unittest.main()
