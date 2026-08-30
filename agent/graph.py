from __future__ import annotations

from agent.nodes.answer_generator import create_answer_generator, generate_answer
from agent.nodes.intent_recognizer import create_intent_recognizer
from agent.nodes.knowledge_validator import validate_knowledge
from agent.nodes.llm_planner import create_semantic_parser
from agent.nodes.planner import plan as build_base_plan
from agent.nodes.rag_retriever import create_rag_retriever
from agent.nodes.retrievability_validator import validate_intent_for_retrieval
from agent.nodes.retrieval_query_builder import build_retrieval_query
from agent.nodes.result_validator import validate_result
from agent.nodes.sql_executor import create_sql_executor
from agent.nodes.sql_generator import generate_sql, validate_sql
from agent.nodes.time_validator import validate_time_semantics
from agent.nodes.validator import validate_plan
from agent.state import AgentState
from smart_ask_data.trace_store import traced_node


def create_retry_node(max_retries: int):
    def retry(state: AgentState) -> AgentState:
        count = state.get("retry_count", 0) + 1
        exhausted = count > max_retries
        return {
            "retry_count": count,
            "retry_action": "FAILED" if exhausted else "REGENERATE_SQL",
            "validation_errors": state.get("validation_errors", []) if exhausted else [],
            "trace": [*state.get("trace", []), "retry_exhausted" if exhausted else f"retry_{count}"]
        }
    return retry


class ScoredWorkflow:
    """Dependency-free execution of the same scored retry graph."""

    def __init__(self, knowledge_client, query_client, max_retries: int, llm_client=None,
                 knowledge_top_n: int = 5, intent_threshold: float = 0.65,
                 knowledge_threshold: float = 0.65, ambiguity_margin: float = 0.10):
        self.recognize_intent = create_intent_recognizer(llm_client)
        self.validate_intent = lambda state: validate_intent_for_retrieval(state, intent_threshold)
        self.build_query = lambda state: build_retrieval_query(state, knowledge_top_n)
        self.retrieve = create_rag_retriever(knowledge_client)
        self.validate_knowledge = lambda state: validate_knowledge(state, knowledge_threshold, ambiguity_margin)
        self.parse_semantics = create_semantic_parser(llm_client)
        self.execute = create_sql_executor(query_client)
        self.answer = create_answer_generator(llm_client)
        self.retry = create_retry_node(max_retries)

    @staticmethod
    def _apply(current: AgentState, stage: str, node) -> None:
        current.update(traced_node(stage, node)(current))

    def invoke(self, state: AgentState) -> AgentState:
        current = dict(state)
        for stage, node in (
            ("intent_recognition", self.recognize_intent),
            ("intent_retrievability_validation", self.validate_intent),
        ):
            self._apply(current, stage, node)
        if current.get("retry_action") == "STOP":
            self._apply(current, "answer_generation", self.answer)
            return current
        for stage, node in (
            ("retrieval_query_building", self.build_query),
            ("knowledge_retrieval", self.retrieve),
            ("knowledge_validation", self.validate_knowledge),
        ):
            self._apply(current, stage, node)
        if current.get("retry_action") == "STOP":
            self._apply(current, "answer_generation", self.answer)
            return current
        for stage, node in (
            ("base_plan_building", build_base_plan),
            ("llm_semantic_parsing", self.parse_semantics),
            ("time_semantic_validation", validate_time_semantics),
        ):
            self._apply(current, stage, node)
        if current.get("retry_action") == "STOP":
            self._apply(current, "answer_generation", self.answer)
            return current
        self._apply(current, "plan_validation", validate_plan)
        if current.get("retry_action") == "STOP":
            self._apply(current, "answer_generation", self.answer)
            return current
        while True:
            for stage, node in (("sql_generation", generate_sql), ("sql_validation", validate_sql)):
                self._apply(current, stage, node)
            if current.get("retry_action") == "CONTINUE":
                for stage, node in (("sql_execution", self.execute), ("result_validation", validate_result)):
                    self._apply(current, stage, node)
            if current.get("retry_action") == "ANSWER":
                break
            self._apply(current, "retry_decision", self.retry)
            if current.get("retry_action") == "FAILED":
                break
        self._apply(current, "answer_generation", self.answer)
        return current


def build_graph(knowledge_client, query_client, max_retries: int = 2, llm_client=None,
                knowledge_top_n: int = 5, intent_threshold: float = 0.65,
                knowledge_threshold: float = 0.65, ambiguity_margin: float = 0.10):
    try:
        from langgraph.graph import END, START, StateGraph
    except ImportError:
        return ScoredWorkflow(knowledge_client, query_client, max_retries, llm_client,
                              knowledge_top_n, intent_threshold, knowledge_threshold, ambiguity_margin)

    graph = StateGraph(AgentState)
    graph.add_node("intent_recognizer", traced_node("intent_recognition", create_intent_recognizer(llm_client)))
    graph.add_node("retrievability_validator", traced_node(
        "intent_retrievability_validation", lambda s: validate_intent_for_retrieval(s, intent_threshold)))
    graph.add_node("retrieval_query_builder", traced_node(
        "retrieval_query_building", lambda s: build_retrieval_query(s, knowledge_top_n)))
    graph.add_node("rag", traced_node("knowledge_retrieval", create_rag_retriever(knowledge_client)))
    graph.add_node("knowledge_validator", traced_node(
        "knowledge_validation", lambda s: validate_knowledge(s, knowledge_threshold, ambiguity_margin)))
    graph.add_node("base_plan_builder", traced_node("base_plan_building", build_base_plan))
    graph.add_node("llm_semantic_parser", traced_node("llm_semantic_parsing", create_semantic_parser(llm_client)))
    graph.add_node("time_semantic_validator", traced_node("time_semantic_validation", validate_time_semantics))
    graph.add_node("plan_validator", traced_node("plan_validation", validate_plan))
    graph.add_node("sql_generator", traced_node("sql_generation", generate_sql))
    graph.add_node("sql_validator", traced_node("sql_validation", validate_sql))
    graph.add_node("sql_executor", traced_node("sql_execution", create_sql_executor(query_client)))
    graph.add_node("result_validator", traced_node("result_validation", validate_result))
    graph.add_node("retry", traced_node("retry_decision", create_retry_node(max_retries)))
    graph.add_node("answer_generator", traced_node("answer_generation", create_answer_generator(llm_client)))

    graph.add_edge(START, "intent_recognizer")
    graph.add_edge("intent_recognizer", "retrievability_validator")
    graph.add_conditional_edges(
        "retrievability_validator", lambda s: "stop" if s.get("retry_action") == "STOP" else "continue",
        {"stop": "answer_generator", "continue": "retrieval_query_builder"}
    )
    graph.add_edge("retrieval_query_builder", "rag")
    graph.add_edge("rag", "knowledge_validator")
    graph.add_conditional_edges(
        "knowledge_validator", lambda s: "stop" if s.get("retry_action") == "STOP" else "continue",
        {"stop": "answer_generator", "continue": "base_plan_builder"}
    )
    graph.add_edge("base_plan_builder", "llm_semantic_parser")
    graph.add_edge("llm_semantic_parser", "time_semantic_validator")
    graph.add_conditional_edges(
        "time_semantic_validator", lambda s: "stop" if s.get("retry_action") == "STOP" else "continue",
        {"stop": "answer_generator", "continue": "plan_validator"}
    )
    graph.add_conditional_edges(
        "plan_validator", lambda s: "stop" if s.get("retry_action") == "STOP" else "continue",
        {"stop": "answer_generator", "continue": "sql_generator"}
    )
    graph.add_edge("sql_generator", "sql_validator")
    graph.add_conditional_edges(
        "sql_validator", lambda s: "execute" if s.get("retry_action") == "CONTINUE" else "retry",
        {"execute": "sql_executor", "retry": "retry"}
    )
    graph.add_edge("sql_executor", "result_validator")
    graph.add_conditional_edges(
        "result_validator", lambda s: "answer" if s.get("retry_action") == "ANSWER" else "retry",
        {"answer": "answer_generator", "retry": "retry"}
    )
    graph.add_conditional_edges(
        "retry", lambda s: "stop" if s.get("retry_action") == "FAILED" else "again",
        {"stop": "answer_generator", "again": "sql_generator"}
    )
    graph.add_edge("answer_generator", END)
    return graph.compile()
