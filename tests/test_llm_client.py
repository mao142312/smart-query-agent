import json
import unittest

from tools.llm_client import OpenAICompatibleLLM


class LLMClientTest(unittest.TestCase):
    def test_chat_instructions_include_the_requested_json_schema(self):
        schema = {
            "type": "object",
            "properties": {"metric_terms": {"type": "array", "items": {"type": "string"}}},
            "required": ["metric_terms"],
            "additionalProperties": False,
        }

        instructions = OpenAICompatibleLLM._chat_instructions(
            "提取查询意图。", "query_intent", schema,
        )

        self.assertIn("query_intent", instructions)
        self.assertIn(json.dumps(schema, ensure_ascii=False), instructions)
        self.assertIn("只能输出一个符合该 Schema 的 JSON 对象", instructions)


if __name__ == "__main__":
    unittest.main()
