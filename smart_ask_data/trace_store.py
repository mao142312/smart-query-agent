from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from smart_ask_data.config import ROOT


TRACE_ROOT = ROOT / "log"


def _safe_name(value: str, limit: int = 48) -> str:
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", value.strip())
    value = re.sub(r"\s+", "_", value).strip("._")
    return (value or "empty-question")[:limit]


def _json_value(value: Any) -> Any:
    try:
        json.dumps(value, ensure_ascii=False)
        return value
    except (TypeError, ValueError):
        if isinstance(value, dict):
            return {str(key): _json_value(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [_json_value(item) for item in value]
        return str(value)


def create_question_trace(question: str, request_id: str) -> Path:
    now = datetime.now().astimezone()
    folder = TRACE_ROOT / now.strftime("%Y-%m-%d") / (
        f"{now.strftime('%H%M%S_%f')[:-3]}__{_safe_name(question)}__{request_id[:8]}"
    )
    folder.mkdir(parents=True, exist_ok=False)
    write_json(folder / "00_question.json", {
        "request_id": request_id,
        "question": question,
        "started_at": now.isoformat(),
    })
    return folder


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(_json_value(payload), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def write_stage(trace_dir: str | Path, stage: str, state_before: dict, produced: dict) -> None:
    folder = Path(trace_dir)
    sequence = len(list(folder.glob("[0-9][0-9]_*_result.json"))) + 1
    state_after = {**state_before, **produced}
    write_json(folder / f"{sequence:02d}_{stage}_result.json", {
        "request_id": state_before.get("request_id"),
        "question": state_before.get("question"),
        "stage": stage,
        "sequence": sequence,
        "retry_count": state_after.get("retry_count", 0),
        "produced": produced,
        "state_after": state_after,
        "recorded_at": datetime.now().astimezone().isoformat(),
    })


def traced_node(stage: str, node: Callable) -> Callable:
    def run(state: dict) -> dict:
        produced = node(state)
        trace_dir = state.get("trace_log_dir")
        if trace_dir:
            write_stage(trace_dir, stage, state, produced)
        return produced

    run.__name__ = f"traced_{stage}"
    return run


def write_summary(trace_dir: str | Path, result: dict, status: str) -> None:
    write_json(Path(trace_dir) / "99_summary.json", {
        "request_id": result.get("request_id"),
        "question": result.get("question"),
        "status": status,
        "answer": result.get("answer"),
        "scores": result.get("scores", {}),
        "sql_history": result.get("sql_history", []),
        "trace": result.get("trace", []),
        "completed_at": datetime.now().astimezone().isoformat(),
    })


def write_failure(trace_dir: str | Path, request_id: str, question: str, error: Exception) -> None:
    write_json(Path(trace_dir) / "99_failure.json", {
        "request_id": request_id,
        "question": question,
        "status": "failed",
        "error_type": type(error).__name__,
        "error": str(error),
        "failed_at": datetime.now().astimezone().isoformat(),
    })
