# AI 意图驱动问数工作流设计

## 1. 目标

将当前“原始问题直接检索知识库”的流程改为：先由 AI 抽取结构化用户意图，再基于结构化线索召回 Top N 企业知识，最后结合原问题、意图和候选知识生成可执行查询计划与 SQL。

本次改造保持现有 API、SQL 安全校验、执行引擎、结果评分和回答结构兼容，不引入新的外部依赖。

## 2. 目标流程

```text
用户问题
→ AI 意图识别
→ 意图可检索性校验
   ├─ 不具备检索条件：生成澄清回答并结束
   └─ 通过
→ 构建结构化知识检索条件
→ 知识库 Top N 检索
→ 候选知识可靠性校验
   ├─ 无可靠候选：生成澄清或不支持说明并结束
   └─ 通过
→ 基础计划构建
→ Grounded LLM 逻辑规划
→ 时间语义校验
→ 计划口径校验
→ SQL 生成与校验
→ SQL 执行与结果校验
→ 有限重试
→ 回答生成与可信度判断
```

## 3. 模块设计

### 3.1 Intent Recognizer

新增 `agent/nodes/intent_recognizer.py`，只负责理解用户原话，不得臆造数据库表、字段或正式指标 ID。

输入：

```python
{
    "question": str,
    "reference_date": str,
}
```

输出 `intent`：

```python
{
    "query_type": str,
    "metric_terms": list[str],
    "business_objects": list[dict],
    "actions": list[str],
    "dimension_terms": list[str],
    "member_terms": list[str],
    "time_expression": str | None,
    "grouping_terms": list[str],
    "calculation_intent": str | None,
    "ambiguities": list[dict],
    "confidence": float,
    "source": "llm" | "raw_question_fallback",
}
```

没有配置 LLM 或模型调用失败时，使用原始问题构造降级意图，但标记低置信度；降级意图仍允许本地关键词知识库工作，后续规划阶段按现有规则决定是否停止。

### 3.2 Retrievability Validator

新增 `validate_intent_for_retrieval(state)`。该节点不判断最终业务口径是否正确，只判断当前意图是否包含足够线索用于检索企业知识：

- 根据 `query_type` 应用不同必填规则；
- 至少存在指标描述、业务对象或业务动作中的一个有效检索目标；
- 必要实体包含非空原文，但不要求检索前已有正式实体 ID；
- 时间是否必填由查询类型决定，指标定义查询不强制时间，趋势查询必须有时间范围；
- 区分阻塞性歧义和可通过知识检索消解的业务术语歧义；
- 输出规则评分、缺失字段、阻塞性歧义、检索提示和澄清问题。

输出契约：

```python
{
    "retrievable": bool,
    "score": float,
    "checks": list[dict],
    "missing_fields": list[str],
    "blocking_ambiguities": list[dict],
    "retrieval_hints": list[str],
    "clarification_question": str | None,
}
```

失败时写入 `retry_action="STOP"` 和 `clarification_needed=True`，随后进入回答生成节点，返回针对缺失字段的澄清问题。

首版不让系统在没有用户新信息时自动循环意图识别，避免重复调用得到相同结果。

### 3.3 Structured Retrieval Query Builder

新增纯函数 `build_retrieval_query(state)`，将意图转换为知识检索接口：

```python
{
    "original_question": str,
    "query_texts": list[str],
    "metric_terms": list[str],
    "business_object_terms": list[str],
    "action_terms": list[str],
    "dimension_terms": list[str],
    "member_terms": list[str],
    "desired_knowledge_types": ["metric", "dimension", "business_definition"],
    "top_n": int,
}
```

该节点不选择最终指标，只生产召回线索。

### 3.4 Knowledge Retrieval

修改 `LocalKnowledgeClient.search()`，接受结构化查询并返回按分数降序排列的 Top N：

```python
{
    "metrics": list[dict],
    "dimensions": list[dict],
    "tables": list[dict],
    "retrieval_score": float,
    "retrieval_query": dict,
    "top_n": int,
}
```

当前本地 Mock 使用名称、别名、描述、成员与多个结构化线索的加权匹配；接口边界保持可替换，未来可以接入 Embedding/Qdrant。每个候选保留独立 `retrieval_score`。

### 3.5 Knowledge Validator

新增 `validate_knowledge(state)`：

- 至少召回一个指标候选；
- Top 1 分数达到最低阈值；
- 记录 Top 1 与 Top 2 分差，分差不足时标记候选歧义；
- 验证候选定义含来源表、计算口径和支持维度。

无可靠候选时进入回答生成，说明未识别到支持的指标；多个相近候选无法区分时请求用户明确指标口径。首版不进行无信息增量的自动检索循环。

### 3.6 Grounded Logical Plan Generator

保留现有基础计划构建节点作为确定性兜底；修改 `create_semantic_parser()` 的模型输入，使其同时包含：

```python
{
    "question": str,
    "intent": dict,
    "reference_date": str,
    "timezone": str,
    "metrics": list[dict],
    "dimensions": list[dict],
}
```

模型只能从 Top N 候选中选择正式指标和维度。模型输出仍采用严格 JSON Schema，并映射为当前 `plan`，因此后续 SQL 生成器不直接依赖自然语言输出。

### 3.7 SQL、执行、结果与回答

以下现有节点继续保留：

- 时间语义校验；
- 查询计划校验；
- 确定性 SQL 生成；
- SQL 只读、白名单表、强制过滤、范围和表达式校验；
- SQLite/Trino 执行；
- 结果完整性与业务范围校验；
- SQL/结果有限重试；
- 最终自然语言回答。

SQL 重试仍从 SQL 生成节点开始，不重新调用意图模型和知识检索。意图或知识不可靠时不进入 SQL 阶段。

## 4. Graph 连接

LangGraph 与无 LangGraph 的 `ScoredWorkflow` 必须保持相同顺序：

```text
START
→ intent_recognizer
→ retrievability_validator
   ├─ STOP → answer_generator
   └─ CONTINUE → retrieval_query_builder
→ rag
→ knowledge_validator
   ├─ STOP → answer_generator
   └─ CONTINUE → base_plan_builder
→ grounded_plan_generator
→ time_semantic_validator
→ plan_validator
→ sql_generator
→ sql_validator
→ sql_executor
→ result_validator
→ retry（按现有 max_retries）
→ answer_generator
→ END
```

## 5. 状态模型

在 `AgentState` 中新增：

```python
intent: dict[str, Any]
retrievability_validation: dict[str, Any]
intent_llm_request: dict[str, Any]
intent_llm_response: dict[str, Any] | None
retrieval_query: dict[str, Any]
knowledge_validation: dict[str, Any]
clarification_needed: bool
```

现有 `question`、`knowledge`、`plan`、`scores`、`score_details`、`retry_action`、`sql`、`rows` 和 `answer` 保持兼容。

## 6. 配置

在 `AppSettings` 中增加以下配置，并提供保守默认值：

```python
knowledge_top_n: int = 5
intent_retrievability_threshold: float = 0.65
knowledge_candidate_threshold: float = 0.65
knowledge_ambiguity_margin: float = 0.10
```

允许通过 YAML 和环境变量覆盖。Top N 默认取 5，不新增独立模型配置，意图识别与 grounded planner 暂时复用现有 `llm_client`。

## 7. 可观测性与响应兼容

- 所有新增节点继续通过 `traced_node()` 写入阶段日志；
- `trace` 增加 `intent_recognized`、`intent_retrievability_scored`、`retrieval_query_built`、`knowledge_scored`；
- Debug 响应的 validation report 增加意图和知识检索依据；
- 正常 API 返回结构保持兼容，不强制增加新的顶层响应字段；
- 模型请求、模型响应和结构化检索条件只在 Debug/追踪信息中暴露。

## 8. 错误与安全策略

- 模型输出必须通过 JSON Schema；
- 模型不得输出或决定未经知识库验证的表名、字段名和指标 ID；
- 意图、知识或计划任一阶段不可靠时禁止生成 SQL；
- SQL 继续由确定性生成器构造；
- 所有 SQL 继续执行现有安全校验；
- 重试耗尽后生成可解释的失败回答，不返回未经验证的数据。

## 9. 测试验收

必须覆盖：

1. AI 意图识别发生在知识检索之前；
2. 知识客户端收到结构化查询而不是原始字符串；
3. Top N 数量与排序正确；
4. grounded planner 同时收到原问题、意图和候选知识；
5. 意图不具备可检索条件时不调用知识库和 SQL；
6. 知识候选为空或歧义过高时不生成 SQL；
7. 模型不可用时的降级行为可解释；
8. 原有时间解析、SQL 安全、执行、结果评分和重试测试继续通过；
9. LangGraph 与 `ScoredWorkflow` 的行为一致。

## 10. 非目标

- 本次不训练或微调专用意图模型；
- 本次不接入真实 Qdrant/Embedding 服务；
- 本次不允许 LLM 自由生成 SQL；
- 本次不实现跨多轮会话的澄清状态恢复；
- 本次不重构现有 API 路由或执行引擎。
