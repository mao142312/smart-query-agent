from __future__ import annotations

import json
from typing import Any


class OpenAICompatibleLLM:
    """Real model client supporting OpenAI Responses and compatible Chat Completions APIs."""

    def __init__(self, *, api_key: str, model: str, base_url: str | None = None,
                 api_mode: str = "responses", timeout_seconds: float = 30.0,
                 thinking: str = "enabled"):
        from openai import OpenAI

        self.client = OpenAI(api_key=api_key, base_url=base_url or None, timeout=timeout_seconds)
        self.model = model
        self.api_mode = api_mode
        self.thinking = thinking

    def _extra_body(self) -> dict[str, Any]:
        return {"thinking": {"type": self.thinking}} if self.thinking in {"enabled", "disabled"} else {}

    @staticmethod
    def _chat_instructions(instructions: str, schema_name: str,
                           schema: dict[str, Any]) -> str:
        schema_text = json.dumps(schema, ensure_ascii=False)
        return (
            f"{instructions}\n\n"
            f"输出对象名称：{schema_name}\n"
            f"JSON Schema：{schema_text}\n"
            "只能输出一个符合该 Schema 的 JSON 对象，不得改变字段名、遗漏 required 字段或添加额外字段。"
        )

    def structured(self, *, instructions: str, input_text: str,
                   schema_name: str, schema: dict[str, Any]) -> dict[str, Any]:
        if self.api_mode == "responses":
            response = self.client.responses.create(
                model=self.model,
                instructions=instructions,
                input=input_text,
                text={"format": {"type": "json_schema", "name": schema_name, "schema": schema, "strict": True}},
                store=False,
            )
            return json.loads(response.output_text)
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": self._chat_instructions(instructions, schema_name, schema)},
                {"role": "user", "content": input_text},
            ],
            response_format={"type": "json_object"},
            extra_body=self._extra_body(),
        )
        return json.loads(response.choices[0].message.content or "{}")

    def text(self, *, instructions: str, input_text: str) -> str:
        if self.api_mode == "responses":
            response = self.client.responses.create(
                model=self.model, instructions=instructions, input=input_text, store=False,
            )
            return response.output_text.strip()
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "system", "content": instructions}, {"role": "user", "content": input_text}],
            extra_body=self._extra_body(),
        )
        return (response.choices[0].message.content or "").strip()
