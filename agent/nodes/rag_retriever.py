from agent.state import AgentState


def create_rag_retriever(knowledge_client):
    def retrieve(state: AgentState) -> AgentState:
        knowledge = knowledge_client.search(state["retrieval_query"])
        return {"knowledge": knowledge, "trace": [*state.get("trace", []), "rag_retrieved"]}
    return retrieve
