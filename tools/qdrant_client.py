from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class LocalKnowledgeClient:
    """Qdrant-compatible boundary backed by local JSON for the initial version."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.data = json.loads(self.path.read_text(encoding="utf-8"))

    @staticmethod
    def _score(clues: list[str], item: dict[str, Any]) -> float:
        terms = [item.get("name", ""), item.get("description", ""),
                 *item.get("aliases", []), *item.get("members", [])]
        score = 0.0
        for raw_clue in clues:
            clue = str(raw_clue).strip().lower()
            if not clue:
                continue
            for raw_term in terms:
                term = str(raw_term).strip().lower()
                if not term:
                    continue
                if clue == term:
                    score += 1.0
                elif clue in term or term in clue:
                    score += 0.7
        return round(score, 4)

    def search(self, query: str | dict[str, Any], top_n: int | None = None) -> dict[str, Any]:
        if isinstance(query, str):
            query = {"original_question": query, "query_texts": [query],
                     "metric_terms": [query], "dimension_terms": [], "member_terms": [],
                     "business_object_terms": [], "action_terms": [], "top_n": top_n or 5}
        limit = int(top_n or query.get("top_n", 5))
        metric_clues = [*query.get("query_texts", []), *query.get("metric_terms", []),
                        *query.get("business_object_terms", []), *query.get("action_terms", [])]
        dimension_clues = [*query.get("query_texts", []), *query.get("dimension_terms", []),
                           *query.get("member_terms", [])]
        ranked_metrics = sorted(((self._score(metric_clues, x), x) for x in self.data["metrics"]),
                                key=lambda pair: pair[0], reverse=True)
        ranked_dimensions = sorted(((self._score(dimension_clues, x), x) for x in self.data["dimensions"]),
                                   key=lambda pair: pair[0], reverse=True)
        metric_hits = [(score, x) for score, x in ranked_metrics if score > 0][:limit]
        dimension_hits = [(score, x) for score, x in ranked_dimensions if score > 0][:limit]
        metrics = [{**x, "retrieval_score": score} for score, x in metric_hits]
        dimensions = [{**x, "retrieval_score": score} for score, x in dimension_hits]
        table_names = {x["source"]["table"] for x in metrics}
        tables = [x for x in self.data["tables"] if x["name"] in table_names]
        # Mock 检索仍返回明确的匹配分，真实向量库可直接替换该字段。
        retrieval_score = min(metric_hits[0][0], 1.0) if metric_hits else 0.0
        return {
            "metrics": metrics,
            "dimensions": dimensions,
            "tables": tables,
            "relationships": self.data.get("relationships", []),
            "rules": self.data.get("rules", {}),
            "retrieval_score": retrieval_score,
            "knowledge_version": self.data.get("version"),
            "source": "local-mock", "retrieval_query": query, "top_n": limit,
        }
