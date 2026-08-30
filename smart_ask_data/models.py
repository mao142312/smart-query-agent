from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class AskRequest:
    question: str
    debug: bool = False

    def validate(self) -> None:
        if not self.question or not self.question.strip():
            raise ValueError("question 不能为空")
        if len(self.question) > 1000:
            raise ValueError("question 长度不能超过 1000 个字符")


@dataclass
class AskResponse:
    request_id: str
    answer: str
    confidence: float
    status: str
    sql: str | None = None
    scores: dict[str, float] = field(default_factory=dict)
    score_details: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    sql_history: list[dict[str, Any]] = field(default_factory=list)
    trace: list[str] = field(default_factory=list)
    llm_used: bool = False
    llm_error: str | None = None
    validation_report: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
