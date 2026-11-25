import builtins

import pytest

from agent.graph import build_graph


@pytest.mark.parametrize("failure", [
    ModuleNotFoundError("No module named 'langgraph'", name="langgraph"),
    ImportError("cannot import name 'StateGraph' from 'langgraph.graph'"),
])
def test_build_graph_fails_explicitly_when_required_engine_cannot_import(monkeypatch, failure):
    original_import = builtins.__import__

    def unavailable_engine(name, *args, **kwargs):
        if name == "langgraph.graph":
            raise failure
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", unavailable_engine)
    # Construction must fail, not silently return a different execution engine.
    with pytest.raises(ImportError, match="LangGraph") as caught:
        build_graph(knowledge_client=None, query_client=None)
    assert caught.value.__cause__ is failure
