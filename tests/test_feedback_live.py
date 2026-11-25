"""Opt-in provider smoke test. Never calls a paid/external model in the default suite."""

import json
import os
from contextlib import ExitStack
from pathlib import Path
from time import perf_counter
from urllib.parse import urlsplit

import pytest

from agent.graph import build_graph
from smart_ask_data.config import load_settings
from tests.test_feedback_loop import FeedbackModel, ObservedQuery, invoke
from tools.llm_client import OpenAICompatibleLLM
from tools.qdrant_client import LocalKnowledgeClient


pytestmark = pytest.mark.skipif(
    os.environ.get("SAD_RUN_LIVE_FEEDBACK") != "1",
    reason="Set SAD_RUN_LIVE_FEEDBACK=1 to explicitly enable external model calls",
)


@pytest.mark.parametrize("case", ["metric", "duplicate"])
def test_real_model_consumes_controlled_failure(case, monkeypatch):
    settings = load_settings()
    if not settings.llm.api_key:
        pytest.skip("No model credentials configured")
    assert urlsplit(settings.llm.base_url).hostname == "api.deepseek.com"
    real_model = OpenAICompatibleLLM(
        api_key=settings.llm.api_key, model=settings.llm.model,
        base_url=settings.llm.base_url, api_mode=settings.llm.api_mode,
        timeout_seconds=min(30, settings.llm.timeout_seconds), thinking="disabled",
    )

    class ControlledFailureThenLiveRepair(FeedbackModel):
        def structured(self, **kwargs):
            if kwargs["schema_name"] == "query_plan_repair":
                self.repair_calls.append(json.loads(kwargs["input_text"]))
                return real_model.structured(**kwargs)
            return super().structured(**kwargs)

    with ExitStack() as cleanup:
        cleanup.callback(real_model.client.close)
        real_model.client.max_retries = 0
        endpoint = (real_model.client.responses if settings.llm.api_mode == "responses"
                    else real_model.client.chat.completions)
        original_create = endpoint.create
        request_count = 0

        def bounded_create(**kwargs):
            nonlocal request_count
            if request_count >= 1:
                raise RuntimeError("Live smoke request budget exhausted")
            if len(json.dumps(kwargs, ensure_ascii=False).encode("utf-8")) > 32_000:
                raise RuntimeError("Live smoke input budget exceeded")
            request_count += 1
            limit_key = "max_output_tokens" if settings.llm.api_mode == "responses" else "max_tokens"
            started = perf_counter()
            response = original_create(**kwargs, **{limit_key: 2048})
            usage = response.usage
            # Only numeric billing evidence; never print prompts or raw responses.
            print(json.dumps({
                "case": case, "request_count": request_count,
                "elapsed_seconds": round(perf_counter() - started, 2),
                "input_tokens": getattr(usage, "prompt_tokens", getattr(usage, "input_tokens", None)),
                "output_tokens": getattr(usage, "completion_tokens", getattr(usage, "output_tokens", None)),
                "total_tokens": getattr(usage, "total_tokens", None),
            }))
            return response

        monkeypatch.setattr(endpoint, "create", bounded_create)
        model = ControlledFailureThenLiveRepair(first_error=case)
        query = ObservedQuery("duplicate" if case == "duplicate" else None)
        cleanup.callback(query.database.close)
        knowledge = LocalKnowledgeClient(Path(__file__).parents[1] / "data/mock_knowledge.json")
        app = build_graph(knowledge, query, max_retries=2, llm_client=model)
        question = "昨天各地区开户人数是多少？" if case == "duplicate" else "昨天香港开户人数是多少？"
        result = invoke(app, question, request_id=f"live-smoke-{case}")
        # Assertions only expose safe status; never dump SDK exceptions/credentials.
        assert result.get("repair_outcome") == "revised", result.get("repair_outcome")
        assert result["retry_action"] == "ANSWER"
        assert result["retry_count"] == 1
        assert request_count == 1
        assert len(model.repair_calls) == 1
        assert model.repair_calls[0]["retry_feedback"]["round"] == 1
        if case == "duplicate":
            assert model.repair_calls[0]["retry_feedback"]["previous_sql"] == query.calls[0]
        assert len(query.calls) == (2 if case == "duplicate" else 1)
        assert result["feedback_history"][0]["previous_proposal"]["metric_id"] == (
            "invented_metric" if case == "metric" else "account_open_user_count"
        )
