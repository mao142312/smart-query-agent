from agent.state import AgentState


def create_sql_executor(query_client):
    def execute(state: AgentState) -> AgentState:
        try:
            rows = query_client.execute(state["sql"])
            return {"rows": rows, "execution_error": "", "trace": [*state.get("trace", []), "sql_executed"]}
        except Exception as exc:
            return {"rows": [], "execution_error": str(exc), "trace": [*state.get("trace", []), "sql_execution_failed"]}
    return execute
