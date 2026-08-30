from __future__ import annotations

from agent.state import AgentState


def _unique(values):
    return list(dict.fromkeys(str(x).strip() for x in values if str(x).strip()))


def build_retrieval_query(state: AgentState, top_n: int = 5) -> AgentState:
    intent = state.get("intent", {})
    objects = _unique(x.get("text", "") for x in intent.get("business_objects", []))
    metrics = _unique(intent.get("metric_terms", []))
    actions = _unique(intent.get("actions", []))
    dimensions = _unique(intent.get("dimension_terms", []))
    members = _unique(intent.get("member_terms", []))
    combined = " ".join(_unique([*objects, *metrics, *dimensions, *members]))
    query = {"original_question": state["question"],
             "query_texts": _unique([state["question"], combined]),
             "metric_terms": metrics, "business_object_terms": objects,
             "action_terms": actions, "dimension_terms": dimensions,
             "member_terms": members,
             "desired_knowledge_types": ["metric", "dimension", "business_definition"],
             "top_n": int(top_n)}
    return {"retrieval_query": query,
            "trace": [*state.get("trace", []), "retrieval_query_built"]}
