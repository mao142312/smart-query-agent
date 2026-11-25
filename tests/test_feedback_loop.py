import copy
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from agent.graph import build_graph
from tests.fake_semantic_llm import FakeSemanticLLM
from tools.qdrant_client import LocalKnowledgeClient
from tools.trino_client import SQLiteDemoClient


class FeedbackModel(FakeSemanticLLM):
    """External model substitute: only corrects a proposal after receiving feedback."""

    def __init__(self, first_error="metric", repair="revise"):
        self.first_error = first_error
        self.repair = repair
        self.plan_calls = []
        self.repair_calls = []
        self.repair_instructions = []

    def structured(self, **kwargs):
        payload = json.loads(kwargs["input_text"])
        if kwargs["schema_name"] == "query_plan_repair":
            self.repair_calls.append(payload)
            self.repair_instructions.append(kwargs["instructions"])
            if self.repair == "raise":
                raise TimeoutError("password=secret-fixture repair timeout")
            if self.repair == "malformed":
                return {"action": "REVISE", "proposal": {"metric_id": "account_open_user_count"}}
            if self.repair == "stop":
                return {"action": "STOP", "reason": "缺少修复依据", "proposal": None}
            previous = payload["retry_feedback"]["previous_proposal"]
            proposal = copy.deepcopy(previous)
            if self.repair != "unchanged":
                proposal["metric_id"] = "account_open_user_count"
                proposal["group_by"] = list(dict.fromkeys(proposal["group_by"]))
            if self.repair == "drop_filter":
                proposal["dimension_filters"] = {}
            if self.repair == "change_time":
                proposal["start_date"] = proposal["end_date"] = "2000-01-01"
            if self.repair == "change_metric":
                proposal["metric_id"] = "successful_transaction_amount"
            if self.repair == "extra_sql":
                proposal["sql"] = "SELECT 1"
            return {"action": "REVISE", "reason": "根据反馈修正无效标识或重复分组", "proposal": proposal}
        proposal = super().structured(**kwargs)
        if kwargs["schema_name"] == "query_plan":
            self.plan_calls.append(payload)
            if self.first_error == "metric":
                proposal["metric_id"] = "invented_metric"
            elif self.first_error == "duplicate":
                proposal["group_by"] = ["region", "region"]
        return proposal


class ObservedQuery:
    def __init__(self, error=None):
        self.database = SQLiteDemoClient()
        self.calls = []
        self.error = error

    def execute(self, sql):
        self.calls.append(sql)
        if self.error == "empty":
            return []
        if self.error == "duplicate" and "region AS region, region AS region" in sql:
            # Emulate an engine that rejects repeated output column names.
            raise RuntimeError("DUPLICATE_COLUMN_NAME: region; password=secret-fixture")
        if self.error and self.error not in {"empty", "duplicate"}:
            raise RuntimeError(self.error)
        return self.database.execute(sql)


@pytest.fixture
def workflow_factory():
    queries = []

    def build(model, error=None, budget=2):
        knowledge = LocalKnowledgeClient(Path(__file__).parents[1] / "data/mock_knowledge.json")
        query = ObservedQuery(error)
        queries.append(query)
        app = build_graph(knowledge, query, max_retries=budget, llm_client=model)
        return app, query

    yield build
    for query in queries:
        query.database.close()


def invoke(app, question="昨天香港开户人数是多少？", request_id="test-request"):
    return app.invoke({"question": question, "request_id": request_id, "trace": [], "retry_count": 0})


def test_plan_failure_reaches_actual_next_model_request_and_revalidates(workflow_factory):
    model = FeedbackModel()
    app, query = workflow_factory(model)
    result = invoke(app)
    assert len(model.repair_calls) == 1
    payload = model.repair_calls[0]
    feedback = payload["retry_feedback"]
    assert payload["question"] == "昨天香港开户人数是多少？"
    assert payload["reference_date"] == model.plan_calls[0]["reference_date"]
    assert feedback["round"] == 1
    assert feedback["stage"] == "plan_validation"
    assert feedback["previous_proposal"]["metric_id"] == "invented_metric"
    assert feedback["previous_sql"] is None
    assert feedback["issues"]
    assert result["retry_count"] == 1
    assert result["retry_action"] == "ANSWER"
    assert result["plan"]["metric"]["metric_id"] == "account_open_user_count"
    assert result["trace"].count("time_semantics_validated") == 2
    assert result["trace"].count("plan_scored") == 2
    assert len(query.calls) == 1
    assert result["rows"][0]["value"] >= 0
    assert "无法可靠回答" not in result["answer"]


def test_execution_feedback_includes_sql_and_effective_revision(workflow_factory):
    model = FeedbackModel(first_error="duplicate")
    app, query = workflow_factory(model, "duplicate")
    result = invoke(app, "昨天各地区开户人数是多少？")
    assert len(model.repair_calls) == 1
    feedback = model.repair_calls[0]["retry_feedback"]
    assert feedback["stage"] == "sql_execution"
    assert feedback["previous_sql"] == query.calls[0]
    assert feedback["previous_plan"]["group_by"] == ["region", "region"]
    assert "DUPLICATE_COLUMN_NAME" in json.dumps(feedback)
    assert "secret-fixture" not in json.dumps(model.repair_calls)
    assert len(query.calls) == 2
    assert query.calls[0] != query.calls[1]
    assert result["retry_action"] == "ANSWER"
    assert result["plan"]["group_by"] == ["region"]
    assert len(result["sql_history"]) == 2
    assert result["sql_history"][1]["issues"] == []
    assert result["execution_error"] == ""


@pytest.mark.parametrize("repair", ["unchanged", "stop", "malformed", "raise", "extra_sql"])
def test_invalid_or_ineffective_repair_stops_without_execution(workflow_factory, repair):
    model = FeedbackModel(repair=repair)
    app, query = workflow_factory(model, budget=99)
    result = invoke(app)
    assert len(model.repair_calls) == 1
    assert result["retry_count"] == 1
    assert result["retry_action"] == "FAILED"
    assert query.calls == []
    assert result["validation_errors"]
    assert "无法可靠回答" in result["answer"]
    assert "secret-fixture" not in result["answer"]


@pytest.mark.parametrize("repair", ["drop_filter", "change_time", "change_metric"])
def test_repair_cannot_change_original_query_constraints(workflow_factory, repair):
    model = FeedbackModel(first_error="duplicate", repair=repair)
    app, query = workflow_factory(model, "duplicate")
    result = invoke(app, "昨天香港开户人数按各地区列出")
    assert len(model.repair_calls) == 1
    assert len(query.calls) == 1
    assert result["retry_action"] == "FAILED"
    assert result["plan"]["filters"]["dimensions"] == {"region": "香港"}
    assert result["plan"]["metric"]["metric_id"] == "account_open_user_count"


@pytest.mark.parametrize("error", ["empty", "Access Denied: forbidden", "no such table: missing",
                                  "data partition not ready", "connection timeout"])
def test_unrecoverable_observation_does_not_replan_or_repeat(workflow_factory, error):
    model = FeedbackModel(first_error=None)
    app, query = workflow_factory(model, error)
    result = invoke(app)
    assert len(query.calls) == 1
    assert model.repair_calls == []
    assert result["retry_count"] == 0
    assert result["retry_action"] == "FAILED"
    assert len(result["feedback_history"]) == 1


def test_one_repair_budget_even_if_config_allows_more(workflow_factory):
    model = FeedbackModel()
    app, query = workflow_factory(model, "DUPLICATE_COLUMN_NAME: region", budget=99)
    result = invoke(app)
    assert len(model.repair_calls) == 1
    assert len(query.calls) == 1
    assert result["retry_count"] == 1
    assert result["retry_action"] == "FAILED"
    assert len(result["feedback_history"]) == 2


def test_zero_budget_disables_repair(workflow_factory):
    model = FeedbackModel()
    app, query = workflow_factory(model, budget=0)
    result = invoke(app)
    assert model.repair_calls == []
    assert query.calls == []
    assert result["retry_count"] == 0
    assert result["retry_action"] == "FAILED"


def test_feedback_is_per_invocation_and_first_round_stays_clean(workflow_factory):
    model = FeedbackModel()
    app, query = workflow_factory(model)
    first = invoke(app)
    saved = copy.deepcopy(first["feedback_history"])
    model.first_error = None
    second = invoke(app, request_id="another-request")
    assert first["feedback_history"] == saved
    assert second.get("feedback_history", []) == []
    assert second["retry_count"] == 0
    assert second["retry_action"] == "ANSWER"
    assert "retry_feedback" not in model.plan_calls[-1]
    assert len(model.repair_calls) == 1
    assert len(query.calls) == 2


def test_success_does_not_add_model_call(workflow_factory):
    model = FeedbackModel(first_error=None)
    app, query = workflow_factory(model)
    result = invoke(app)
    assert result["retry_action"] == "ANSWER"
    assert len(query.calls) == 1
    assert len(model.plan_calls) == 1
    assert model.repair_calls == []


def test_generator_failure_is_reported_without_replanning(workflow_factory):
    model = FeedbackModel(first_error=None)
    app, query = workflow_factory(model)
    with patch("agent.nodes.sql_generator.AGGREGATIONS", {}):
        result = invoke(app)
    assert result["retry_action"] == "FAILED"
    assert result["feedback_history"][0]["stage"] == "sql_generation"
    assert query.calls == []
    assert model.repair_calls == []


def test_sql_rejection_does_not_invoke_model_to_bypass_validator(workflow_factory):
    model = FeedbackModel(first_error=None)
    app, query = workflow_factory(model)
    with patch("agent.nodes.sql_generator.AGGREGATIONS", {"count_distinct": lambda *_: "COUNT(*);"}):
        result = invoke(app)
    assert result["retry_action"] == "FAILED"
    assert result["feedback_history"][0]["stage"] == "sql_validation"
    assert model.repair_calls == []
    assert query.calls == []


def test_oversized_feedback_never_enters_model(workflow_factory):
    model = FeedbackModel()
    original = model.structured

    def oversized(**kwargs):
        proposal = original(**kwargs)
        if kwargs["schema_name"] == "query_plan":
            proposal["time_expression"] = "a" * 80000
        return proposal

    model.structured = oversized
    app, query = workflow_factory(model)
    result = invoke(app)
    assert model.repair_calls == []
    assert result["retry_action"] == "FAILED"
    assert result["repair_outcome"] == "context_too_large"
    assert len(json.dumps(result["feedback_history"])) < 40000
    assert query.calls == []


def test_second_execution_failure_retains_both_observations(workflow_factory):
    model = FeedbackModel(first_error="duplicate")
    app, query = workflow_factory(model, "duplicate")
    real_execute = query.execute

    def fail_again(sql):
        if len(query.calls) == 1:
            query.calls.append(sql)
            raise RuntimeError("unexpected target engine failure")
        return real_execute(sql)

    query.execute = fail_again
    result = invoke(app, "昨天各地区开户人数是多少？")
    assert result["retry_action"] == "FAILED"
    assert len(query.calls) == 2
    assert len(model.repair_calls) == 1
    assert [item["round"] for item in result["feedback_history"]] == [1, 2]
    assert result["feedback_history"][0]["previous_plan"]["group_by"] == ["region", "region"]
    assert result["feedback_history"][1]["previous_plan"]["group_by"] == ["region"]


def test_structured_credentials_are_redacted_before_model_call(workflow_factory):
    model = FeedbackModel(first_error="duplicate")
    error = 'DUPLICATE_COLUMN_NAME: region; {"password": "secret with spaces", "api_key": "key-fixture"}'
    app, query = workflow_factory(model, error)
    result = invoke(app, "昨天各地区开户人数是多少？")
    assert len(model.repair_calls) == 1
    transmitted = json.dumps(model.repair_calls, ensure_ascii=False)
    assert "secret with spaces" not in transmitted
    assert "key-fixture" not in transmitted
    assert "secret with spaces" not in json.dumps(result["feedback_history"])
    assert len(query.calls) <= 2


@pytest.mark.parametrize("header", [
    "Authorization: Basic Zml4dHVyZTpzZWNyZXQ=",
    '"Proxy-Authorization": "Basic Zml4dHVyZTpzZWNyZXQ="',
])
def test_auth_headers_are_not_sent_as_feedback(workflow_factory, header):
    model = FeedbackModel(first_error="duplicate")
    app, _ = workflow_factory(model, f"DUPLICATE_COLUMN_NAME: region; {header}")
    result = invoke(app, "昨天各地区开户人数是多少？")
    assert len(model.repair_calls) == 1
    assert "Zml4dHVyZTpzZWNyZXQ=" not in json.dumps(model.repair_calls)
    assert "Zml4dHVyZTpzZWNyZXQ=" not in json.dumps(result["feedback_history"])
