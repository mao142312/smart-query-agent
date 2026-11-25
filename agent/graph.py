from __future__ import annotations

from agent.nodes.answer_generator import create_answer_generator
from agent.nodes.feedback_repair import create_feedback_repairer
from agent.nodes.intent_recognizer import create_intent_recognizer
from agent.nodes.knowledge_validator import validate_knowledge
from agent.nodes.llm_planner import create_semantic_parser
from agent.nodes.planner import plan as build_base_plan
from agent.nodes.rag_retriever import create_rag_retriever
from agent.nodes.result_validator import validate_result
from agent.nodes.retrievability_validator import validate_intent_for_retrieval
from agent.nodes.retrieval_query_builder import build_retrieval_query
from agent.nodes.sql_executor import create_sql_executor
from agent.nodes.sql_generator import generate_sql_safely, validate_sql
from agent.nodes.time_validator import validate_time_semantics
from agent.nodes.validator import validate_plan
from agent.state import AgentState
from smart_ask_data.trace_store import traced_node


def create_retry_node(max_retries: int, llm_client=None):
    return create_feedback_repairer(max_retries, llm_client)


def build_graph(knowledge_client, query_client, max_retries: int = 2, llm_client=None,
                knowledge_top_n: int = 5, intent_threshold: float = 0.65,
                knowledge_threshold: float = 0.65, ambiguity_margin: float = 0.10):
    """Build the sole supported workflow engine; LangGraph is required."""
    try:
        from langgraph.graph import END, START, StateGraph
    except ImportError as exc:
        raise ImportError(
            "LangGraph 是必需的工作流依赖，无法导入。"
            "请在当前 Python 环境安装或修复项目依赖：python -m pip install -e ."
        ) from exc

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
    graph.add_node("sql_generator", traced_node("sql_generation", generate_sql_safely))
    graph.add_node("sql_validator", traced_node("sql_validation", validate_sql))
    graph.add_node("sql_executor", traced_node("sql_execution", create_sql_executor(query_client)))
    graph.add_node("result_validator", traced_node("result_validation", validate_result))
    graph.add_node("retry", traced_node("retry_decision", create_retry_node(max_retries, llm_client)))
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
        {"stop": "retry", "continue": "sql_generator"}
    )
    graph.add_conditional_edges(
        "sql_generator", lambda s: "validate" if s.get("retry_action") == "CONTINUE" else "retry",
        {"validate": "sql_validator", "retry": "retry"}
    )
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
        {"stop": "answer_generator", "again": "time_semantic_validator"}
    )
    graph.add_edge("answer_generator", END)
    return graph.compile()
