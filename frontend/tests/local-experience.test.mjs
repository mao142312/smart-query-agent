import assert from "node:assert/strict";
import test from "node:test";

import { askQuestion } from "../app/ask-api.ts";
import { selectHomeSurface } from "../app/runtime-policy.ts";

test("development renders the analytics surface while production remains in maintenance", () => {
  assert.equal(selectHomeSurface("development"), "analytics");
  assert.equal(selectHomeSurface("production"), "maintenance");
  assert.equal(selectHomeSurface("test"), "maintenance");
});

test("askQuestion sends the local API contract and returns its answer", async () => {
  const calls = [];
  const fetcher = async (url, init) => {
    calls.push({ url, init });
    return new Response(
      JSON.stringify({
        request_id: "req-1",
        answer: "最近一个月业绩为 100 万元。",
        confidence: 0.92,
        status: "success",
        sql: "SELECT 1",
      }),
      { status: 200, headers: { "content-type": "application/json" } },
    );
  };

  const result = await askQuestion("查询齐鑫涛最近一个月业绩", fetcher);

  assert.equal(result.answer, "最近一个月业绩为 100 万元。");
  assert.equal(result.confidence, 0.92);
  assert.equal(calls.length, 1);
  assert.equal(calls[0].url, "/api/v1/ask");
  assert.equal(calls[0].init.method, "POST");
  assert.equal(calls[0].init.headers["Content-Type"], "application/json");
  assert.equal(
    calls[0].init.body,
    JSON.stringify({ question: "查询齐鑫涛最近一个月业绩" }),
  );
});

test("askQuestion exposes a useful backend error", async () => {
  const fetcher = async () =>
    new Response(JSON.stringify({ detail: "service unavailable" }), {
      status: 503,
      headers: { "content-type": "application/json" },
    });

  await assert.rejects(
    askQuestion("查询业绩", fetcher),
    /service unavailable/,
  );
});
