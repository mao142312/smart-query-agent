# AI Intent-Grounded Workflow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rewire the question-to-SQL workflow so AI intent extraction precedes structured Top N knowledge retrieval and grounded logical planning.

**Architecture:** Add focused intent-recognition, retrievability-validation, retrieval-query-building, and knowledge-validation nodes before the existing planning and SQL pipeline. Keep SQL generation deterministic and preserve both LangGraph and dependency-free `ScoredWorkflow` execution paths.

**Tech Stack:** Python 3.12+, TypedDict, unittest, LangGraph when installed, existing OpenAI-compatible structured-output client, local JSON knowledge backend.

**Spec:** `docs/superpowers/specs/2026-08-30-ai-intent-grounded-workflow-design.md`

## Global Constraints

- Intent recognition must not invent formal metric IDs, table names, or column names.
- Knowledge retrieval must receive a structured query and return at most `knowledge_top_n=5` candidates by default.
- Pre-retrieval validation answers only “is this intent searchable?”, not “is the final business meaning correct?”.
- Unsearchable intent or unreliable knowledge must stop before SQL generation and produce an explanatory answer.
- SQL remains deterministic, read-only, bounded, and subject to the existing validation rules.
- SQL/result retries must not repeat intent recognition or knowledge retrieval.
- Existing API response fields remain backward compatible.
- The current workspace is not a Git repository; commit steps are recorded for future use but must be skipped during execution unless Git is initialized by the user.

---

## File Structure

- Create `agent/nodes/intent_recognizer.py`: structured LLM intent extraction and raw-question fallback.
- Create `agent/nodes/retrievability_validator.py`: query-type-aware pre-retrieval rules and clarification generation.
- Create `agent/nodes/retrieval_query_builder.py`: deterministic conversion from intent to retrieval query.
- Create `agent/nodes/knowledge_validator.py`: Top N candidate sufficiency and ambiguity checks.
- Modify `agent/state.py`: add intent, retrieval, validation, and clarification fields.
- Modify `tools/qdrant_client.py`: accept structured retrieval query, score candidates, return Top N.
- Modify `agent/nodes/rag_retriever.py`: pass `state["retrieval_query"]` instead of the raw question.
- Modify `agent/nodes/llm_planner.py`: consume intent plus candidate knowledge and enforce candidate-only selection.
- Modify `agent/nodes/validator.py`: validate the selected metric is one of the retrieved candidates.
- Modify `agent/graph.py`: connect the new nodes in both execution implementations.
- Modify `smart_ask_data/config.py`: add thresholds and Top N configuration.
- Modify `smart_ask_data/factory.py`: pass workflow configuration into graph construction.
- Modify `smart_ask_data/service.py`: expose intent/retrieval evidence in debug validation reports.
- Modify `tests/fake_semantic_llm.py`: return distinct fixtures for intent and grounded-plan schemas.
- Modify `tests/test_workflow.py`: add workflow ordering, stop-path, Top N, grounding, and compatibility tests.
- Modify `tests/test_service.py`: verify debug observability and API compatibility.

---

### Task 1: Intent Recognition State Contract

**Files:**
- Create: `agent/nodes/intent_recognizer.py`
- Modify: `agent/state.py`
- Modify: `tests/fake_semantic_llm.py`
- Test: `tests/test_workflow.py`

**Interfaces:**
- Produces: `create_intent_recognizer(llm_client) -> Callable[[AgentState], AgentState]`
- State output: `intent`, `intent_llm_request`, `intent_llm_response`, trace marker `intent_recognized`.
- Intent schema fields: `query_type`, `metric_terms`, `business_objects`, `actions`, `dimension_terms`, `member_terms`, `time_expression`, `grouping_terms`, `calculation_intent`, `ambiguities`, `confidence`, `source`.

- [ ] **Step 1: Write the failing intent-recognition test**

```python
def test_intent_recognizer_extracts_search_clues_before_knowledge_lookup(self):
    node = create_intent_recognizer(FakeSemanticLLM())
    result = node({"question": "查询齐鑫涛最近一个月业绩", "trace": []})
    self.assertEqual(["业绩"], result["intent"]["metric_terms"])
    self.assertEqual("齐鑫涛", result["intent"]["business_objects"][0]["text"])
    self.assertEqual("最近一个月", result["intent"]["time_expression"])
    self.assertIn("intent_recognized", result["trace"])
```

- [ ] **Step 2: Run the test and verify RED**

Run: `python -m unittest tests.test_workflow.WorkflowTest.test_intent_recognizer_extracts_search_clues_before_knowledge_lookup`

Expected: import failure for `agent.nodes.intent_recognizer` because the production node does not exist.

- [ ] **Step 3: Implement the strict intent schema and node**

Implement `INTENT_SCHEMA` using the existing `llm_client.structured(...)` boundary with `schema_name="query_intent"`. Preserve the user's original words in term fields. On missing model or exception, return:

```python
{
    "query_type": "metric_query",
    "metric_terms": [state["question"]],
    "business_objects": [],
    "actions": [],
    "dimension_terms": [],
    "member_terms": [],
    "time_expression": None,
    "grouping_terms": [],
    "calculation_intent": None,
    "ambiguities": [],
    "confidence": 0.45,
    "source": "raw_question_fallback",
}
```

- [ ] **Step 4: Add the new `AgentState` fields**

```python
intent: dict[str, Any]
intent_llm_request: dict[str, Any]
intent_llm_response: dict[str, Any] | None
retrievability_validation: dict[str, Any]
retrieval_query: dict[str, Any]
knowledge_validation: dict[str, Any]
clarification_needed: bool
```

- [ ] **Step 5: Update `FakeSemanticLLM` by schema name**

When `schema_name == "query_intent"`, return a complete intent fixture. Keep the existing `query_plan` behavior for grounded planning.

- [ ] **Step 6: Run the targeted test and full existing workflow tests**

Run: `python -m unittest tests.test_workflow`

Expected: all tests pass, including the new intent node unit test.

- [ ] **Step 7: Commit if Git is available**

```bash
git add agent/state.py agent/nodes/intent_recognizer.py tests/fake_semantic_llm.py tests/test_workflow.py
git commit -m "feat: add structured intent recognition"
```

---

### Task 2: Query-Type-Aware Retrievability Validation

**Files:**
- Create: `agent/nodes/retrievability_validator.py`
- Test: `tests/test_workflow.py`

**Interfaces:**
- Produces: `validate_intent_for_retrieval(state: AgentState) -> AgentState`
- Output: `retrievability_validation`, `clarification_needed`, `retry_action`, scores/details under key `intent`.

- [ ] **Step 1: Write failing tests for searchable and blocked intent**

```python
def test_metric_term_is_searchable_even_when_business_term_is_ambiguous(self):
    state = {"intent": {
        "query_type": "metric_query", "metric_terms": ["业绩"],
        "business_objects": [{"type_hint": "employee", "text": "齐鑫涛"}],
        "actions": [], "dimension_terms": [], "member_terms": [],
        "time_expression": "最近一个月", "grouping_terms": [],
        "calculation_intent": None,
        "ambiguities": [{"field": "metric", "blocking": False}],
        "confidence": 0.8,
    }}
    result = validate_intent_for_retrieval(state, threshold=0.65)
    self.assertTrue(result["retrievability_validation"]["retrievable"])
    self.assertEqual("CONTINUE", result["retry_action"])

def test_unresolved_reference_stops_before_retrieval(self):
    state = {"intent": {
        "query_type": "metric_query", "metric_terms": ["业绩"],
        "business_objects": [], "actions": [], "dimension_terms": [],
        "member_terms": [], "time_expression": "最近一个月",
        "grouping_terms": [], "calculation_intent": None,
        "ambiguities": [{"field": "business_object", "text": "他", "blocking": True}],
        "confidence": 0.8,
    }}
    result = validate_intent_for_retrieval(state, threshold=0.65)
    self.assertFalse(result["retrievability_validation"]["retrievable"])
    self.assertTrue(result["clarification_needed"])
    self.assertEqual("STOP", result["retry_action"])
```

- [ ] **Step 2: Run both tests and verify RED**

Run: `python -m unittest tests.test_workflow.WorkflowTest.test_metric_term_is_searchable_even_when_business_term_is_ambiguous tests.test_workflow.WorkflowTest.test_unresolved_reference_stops_before_retrieval`

Expected: import failure because the validator does not exist.

- [ ] **Step 3: Implement query-type requirements and weighted checks**

Use literal rules:

```python
QUERY_REQUIREMENTS = {
    "metric_query": {"search_target": True, "time_required": False},
    "definition_query": {"metric_required": True, "time_required": False},
    "trend_query": {"search_target": True, "time_required": True},
    "comparison_query": {"search_target": True, "comparison_required": True},
    "ranking_query": {"search_target": True, "grouping_required": True},
}
```

Hard-stop on missing search target or any `blocking=True` ambiguity. Compute a transparent weighted score and construct one concrete `clarification_question` from the first blocking issue.

- [ ] **Step 4: Run the targeted tests and workflow suite**

Run: `python -m unittest tests.test_workflow`

Expected: all tests pass.

- [ ] **Step 5: Commit if Git is available**

```bash
git add agent/nodes/retrievability_validator.py tests/test_workflow.py
git commit -m "feat: validate intent retrievability"
```

---

### Task 3: Structured Retrieval Query and Top N Knowledge Search

**Files:**
- Create: `agent/nodes/retrieval_query_builder.py`
- Modify: `agent/nodes/rag_retriever.py`
- Modify: `tools/qdrant_client.py`
- Test: `tests/test_workflow.py`

**Interfaces:**
- Produces: `build_retrieval_query(state: AgentState, top_n: int = 5) -> AgentState`
- Changes: `LocalKnowledgeClient.search(query: dict[str, Any], top_n: int | None = None) -> dict[str, Any]`
- `create_rag_retriever` reads `state["retrieval_query"]` only.

- [ ] **Step 1: Write a failing literal query-builder test**

```python
def test_retrieval_query_is_built_from_intent_clues(self):
    result = build_retrieval_query({
        "question": "查询齐鑫涛最近一个月业绩",
        "intent": {
            "metric_terms": ["业绩"],
            "business_objects": [{"type_hint": "employee", "text": "齐鑫涛"}],
            "actions": ["查询"], "dimension_terms": ["员工"],
            "member_terms": ["齐鑫涛"], "grouping_terms": [],
        },
    }, top_n=5)
    self.assertEqual(["业绩"], result["retrieval_query"]["metric_terms"])
    self.assertEqual(["齐鑫涛"], result["retrieval_query"]["member_terms"])
    self.assertEqual(5, result["retrieval_query"]["top_n"])
```

- [ ] **Step 2: Write a failing Top N boundary test**

Construct a temporary knowledge JSON containing three metrics whose aliases match one clue, call `search(query, top_n=2)`, and assert exactly two metrics are returned in descending `retrieval_score` order.

- [ ] **Step 3: Run tests and verify RED**

Run: `python -m unittest tests.test_workflow.WorkflowTest.test_retrieval_query_is_built_from_intent_clues tests.test_workflow.WorkflowTest.test_structured_knowledge_search_returns_ranked_top_n`

Expected: missing builder and incompatible `search` signature failures.

- [ ] **Step 4: Implement deterministic query building**

Deduplicate non-empty terms while preserving order. Generate `query_texts` from the original question plus combinations of metric, object, action, dimension, and member terms. Do not insert metric IDs.

- [ ] **Step 5: Implement weighted local knowledge ranking**

Score against `name`, `aliases`, `description`, and dimension `members`. Give exact name/alias matches more weight than substring matches. Attach per-candidate `retrieval_score`, sort descending, slice to Top N, and preserve source table lookup.

- [ ] **Step 6: Change the RAG node boundary**

```python
def retrieve(state: AgentState) -> AgentState:
    knowledge = knowledge_client.search(state["retrieval_query"])
    return {"knowledge": knowledge, ...}
```

- [ ] **Step 7: Run targeted and full tests**

Run: `python -m unittest tests.test_workflow tests.test_service`

Expected: all tests pass after adapting existing direct `search(str)` tests to the new structured contract. If backward compatibility is retained, cover it explicitly rather than relying on it implicitly.

- [ ] **Step 8: Commit if Git is available**

```bash
git add agent/nodes/retrieval_query_builder.py agent/nodes/rag_retriever.py tools/qdrant_client.py tests/test_workflow.py
git commit -m "feat: add structured top-n knowledge retrieval"
```

---

### Task 4: Knowledge Reliability and Grounded Planning

**Files:**
- Create: `agent/nodes/knowledge_validator.py`
- Modify: `agent/nodes/llm_planner.py`
- Modify: `agent/nodes/validator.py`
- Test: `tests/test_workflow.py`

**Interfaces:**
- Produces: `validate_knowledge(state, threshold, ambiguity_margin) -> AgentState`
- Grounded planner input adds `intent` and consumes only candidates in `knowledge.metrics`/`knowledge.dimensions`.

- [ ] **Step 1: Write failing knowledge validation tests**

Cover three literal cases:

1. empty metric candidates → `STOP`, `clarification_needed=True`;
2. Top 1 score above threshold and clear margin → `CONTINUE`;
3. Top 1 and Top 2 score gap below margin → `STOP` with candidate names in the clarification evidence.

- [ ] **Step 2: Write a failing grounded planner input test**

Use a recording fake LLM and assert the parsed `input_text` contains the exact `intent`, retrieved candidate metric IDs, and original question. Assert a model-selected metric ID outside the candidates produces no selected metric.

- [ ] **Step 3: Run tests and verify RED**

Run: `python -m unittest tests.test_workflow.WorkflowTest.test_empty_knowledge_stops_before_planning tests.test_workflow.WorkflowTest.test_ambiguous_knowledge_requests_clarification tests.test_workflow.WorkflowTest.test_grounded_planner_receives_intent_and_candidates`

Expected: missing knowledge validator and absent `intent` in planner payload.

- [ ] **Step 4: Implement knowledge validation**

Return detailed checks under `knowledge_validation`, update `scores["knowledge"]`, write `retry_action`, and never select a metric in this node.

- [ ] **Step 5: Ground the planner**

Add `intent` to `model_input`. Update instructions to state that formal metrics and dimensions must be chosen only from the supplied candidates. Remove any fallback that silently chooses a candidate when multiple candidates exist and the model selection is invalid.

- [ ] **Step 6: Update plan validation semantics**

Replace “knowledge returned exactly one metric” with “the selected metric ID belongs to the retrieved candidate set”. Keep definition completeness and supported-dimension checks.

- [ ] **Step 7: Run targeted and full tests**

Run: `python -m unittest tests.test_workflow tests.test_service`

Expected: all tests pass.

- [ ] **Step 8: Commit if Git is available**

```bash
git add agent/nodes/knowledge_validator.py agent/nodes/llm_planner.py agent/nodes/validator.py tests/test_workflow.py
git commit -m "feat: ground query planning in retrieved knowledge"
```

---

### Task 5: Rewire LangGraph and ScoredWorkflow

**Files:**
- Modify: `agent/graph.py`
- Modify: `smart_ask_data/config.py`
- Modify: `smart_ask_data/factory.py`
- Test: `tests/test_workflow.py`
- Test: `tests/test_service.py`

**Interfaces:**
- Extend `build_graph(...)` with keyword thresholds/Top N or pass a focused immutable workflow settings object.
- Both execution paths must run identical stages and branching behavior.

- [ ] **Step 1: Write a failing end-to-end ordering test**

Use recording intent LLM and knowledge client. Invoke the real workflow and assert the knowledge client receives a dict containing `metric_terms`, proving intent recognition and query construction occurred before retrieval. Assert trace ordering:

```python
expected_prefix = [
    "intent_recognized",
    "intent_retrievability_scored",
    "retrieval_query_built",
    "rag_retrieved",
    "knowledge_scored",
]
self.assertEqual(expected_prefix, [x for x in result["trace"] if x in expected_prefix])
```

- [ ] **Step 2: Write a failing stop-path test**

Provide an intent fixture with a blocking unresolved reference. Assert the workflow returns an answer, does not call the knowledge client, and does not contain `sql`.

- [ ] **Step 3: Run tests and verify RED**

Run: `python -m unittest tests.test_workflow.WorkflowTest.test_workflow_recognizes_intent_before_retrieval tests.test_workflow.WorkflowTest.test_unsearchable_intent_stops_before_knowledge_and_sql`

Expected: trace ordering and no-call assertions fail against the old graph.

- [ ] **Step 4: Wire the dependency-free workflow**

Run these stages before the existing planning loop:

```python
intent_recognition
intent_retrievability_validation
retrieval_query_building
knowledge_retrieval
knowledge_validation
```

After each validator, route `STOP` to answer generation. Keep SQL/result retries inside the existing loop.

- [ ] **Step 5: Wire the LangGraph path identically**

Add nodes and conditional edges matching the spec. Ensure `START` connects to `intent_recognizer`, not `rag`.

- [ ] **Step 6: Add configuration values**

Support YAML and environment variables:

```text
SAD_KNOWLEDGE_TOP_N=5
SAD_INTENT_RETRIEVABILITY_THRESHOLD=0.65
SAD_KNOWLEDGE_CANDIDATE_THRESHOLD=0.65
SAD_KNOWLEDGE_AMBIGUITY_MARGIN=0.10
```

Pass them from `create_service()` into `build_graph()`.

- [ ] **Step 7: Run workflow and service tests**

Run: `python -m unittest tests.test_workflow tests.test_service`

Expected: all tests pass in the dependency-free environment. If LangGraph is installed, add a narrow equivalence test for both paths.

- [ ] **Step 8: Commit if Git is available**

```bash
git add agent/graph.py smart_ask_data/config.py smart_ask_data/factory.py tests/test_workflow.py tests/test_service.py
git commit -m "feat: rewire workflow around intent-first retrieval"
```

---

### Task 6: Clarification Answers and Debug Observability

**Files:**
- Modify: `agent/nodes/answer_generator.py`
- Modify: `smart_ask_data/service.py`
- Modify: `smart_ask_data/models.py` only if a backward-compatible optional debug field is justified.
- Test: `tests/test_service.py`

**Interfaces:**
- Answer generation consumes `clarification_needed`, validator evidence, and `retry_action`.
- Validation report exposes intent, retrieval query, candidate IDs/scores, and selected metric in debug output.

- [ ] **Step 1: Write failing clarification response tests**

```python
def test_blocking_intent_ambiguity_returns_specific_clarification(self):
    response = service.ask(AskRequest("查一下他最近的业绩", debug=True))
    self.assertEqual("unreliable", response.status)
    self.assertIn("他指的是谁", response.answer)
    self.assertIsNone(response.sql)
```

Also test ambiguous knowledge candidates mention candidate display names and do not expose internal table names.

- [ ] **Step 2: Run tests and verify RED**

Run: `python -m unittest tests.test_service.ServiceTest.test_blocking_intent_ambiguity_returns_specific_clarification`

Expected: current answer generator returns a generic unreliable answer.

- [ ] **Step 3: Implement deterministic clarification precedence**

Before ordinary result answering:

1. use `retrievability_validation.clarification_question`;
2. otherwise use `knowledge_validation.clarification_question`;
3. otherwise preserve existing STOP/FAILED answer behavior.

- [ ] **Step 4: Extend the validation report without breaking normal responses**

Add an `intent` report step and include `retrieval_query`, candidate names/scores, and validation checks. Keep SQL/debug-only fields hidden when `request.debug` is false.

- [ ] **Step 5: Run service and workflow tests**

Run: `python -m unittest tests.test_service tests.test_workflow`

Expected: all tests pass and existing non-debug response assertions remain unchanged except the documented extra validation-report step.

- [ ] **Step 6: Commit if Git is available**

```bash
git add agent/nodes/answer_generator.py smart_ask_data/service.py smart_ask_data/models.py tests/test_service.py
git commit -m "feat: explain intent and knowledge clarification failures"
```

---

### Task 7: Full Verification and Documentation Alignment

**Files:**
- Modify: `README.md` if it documents the old workflow order.
- Modify: `知识库/Resources/系统架构与处理流程.md` if it documents the old workflow order.
- Verify: `AI意图驱动业务流程.drawio`
- Verify: `AI意图驱动业务流程.png`

**Interfaces:** None; this task verifies the integrated behavior and aligns human documentation.

- [ ] **Step 1: Run all unit tests**

Run: `python -m unittest discover -s tests -v`

Expected: zero failures and zero errors.

- [ ] **Step 2: Run compile validation**

Run: `python -m compileall -q agent smart_ask_data tools tests`

Expected: exit code 0 with no syntax errors.

- [ ] **Step 3: Run representative behavior checks**

Verify these observable cases through the real service/workflow:

- clear metric question reaches SQL and produces an answer;
- blocking reference ambiguity stops before knowledge retrieval;
- empty knowledge result stops before SQL;
- ambiguous Top N candidates request clarification;
- SQL and result retries do not add a second `intent_recognized` trace entry.

- [ ] **Step 4: Validate Draw.io XML and workflow labels**

Run an XML parser, verify all edge source/target IDs exist, and regenerate the PNG. Confirm the diagram says `是否具备可检索条件？`.

- [ ] **Step 5: Update human documentation**

Document the final node order, structured retrieval query contract, stop conditions, and configuration environment variables. Do not describe Qdrant as implemented while the backend remains local weighted retrieval.

- [ ] **Step 6: Perform a focused code review**

Review for:

- duplicated node order between LangGraph and `ScoredWorkflow`;
- model-selected IDs escaping the candidate set;
- intent/model internals leaking in non-debug API responses;
- SQL execution reachable from STOP branches;
- retries accidentally repeating intent or knowledge stages.

- [ ] **Step 7: Commit if Git is available**

```bash
git add README.md 知识库/Resources/系统架构与处理流程.md AI意图驱动业务流程.drawio AI意图驱动业务流程.png
git commit -m "docs: document intent-first grounded workflow"
```
