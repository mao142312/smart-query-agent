# M-1 Feedback Decision Loop Implementation Plan

> 历史执行记录：用户随后于 2026-10-11 明确仅支持 LangGraph，以下双引擎任务记录保留为当时证据，不再作为后续验收要求；不得恢复 ScoredWorkflow。当前需求见 `docs/方案设计.md` 的“LangGraph 单引擎修订”。

> **For agentic workers:** Use executing-plans for sequential execution. This is one tightly coupled workflow change; use an independent reviewer after integration. Steps use checkbox syntax.

**Goal:** 上一轮错误及产物进入下一轮实际模型请求；允许一次有约束修复，无变化或不可恢复时明确停止。

**Architecture:** 独立的反馈修复节点保存有界反馈快照、调用结构化模型并保护原始查询约束。复用语义规划的计划构建函数，修订后回到时间/计划/SQL 校验；LangGraph 与 ScoredWorkflow 使用同一修复实现。

**Tech Stack:** Python 3.10+，现有 LLM Client、LangGraph、unittest/pytest、SQLite；不新增依赖，不做 AST。

**Spec:** `docs/方案设计.md` 第 9 节与 `docs/2026-09-29-验证机制分类与里程碑.md` M-1。

## Global Constraints

- 用户同意当前目录新建 `codex/m1-feedback-loop` 分支，保留全部已有修改；不提交其他工作，不发布 v1.1.0。
- 一次自动修复预算；`max_retries=0` 禁用，较大旧配置也不能超过一次模型修复。
- SQL 仍由程序生成，模型不能改指标定义、数据源、授权或限制；不依赖保存内部思维链。
- M-1 保护已有查询约束，不实现 M2 的任意需求理解修正。可纠正未知指标 ID（仅唯一候选）和冗余重复分组；不能删条件、换指标或改日期来通过。
- 无法证明安全的修订停止；空数据、权限拒绝、知识/生成器缺陷不通过盲重试修复。临时连接错误本阶段明确失败，不新增传输重试策略。
- 反馈是数据不是指令；新传递的错误信息脱敏、有长度上限，不发送原始结果行。复用现有业务知识和请求输入，不扩大外发范围。
- 真实模型效果与测试模型契约分开报告；没有真实调用证据不勾选整体验收完成。

## Files and Interfaces

- 新增 `agent/nodes/feedback_repair.py`：`create_feedback_repairer(max_retries, llm_client)` 返回状态节点；构造反馈、修复请求、约束检查与终止原因。
- 修改 `agent/nodes/llm_planner.py`：抽取 `proposal_to_plan(proposal, state)`，固定请求参考日期供首轮和修复复用；不改变首次规划业务语义。
- 修改 `agent/nodes/validator.py`：计划失败写结构化 feedback，供修复节点辨别。
- 修改 `agent/graph.py`：失败转修复，修复成功回到时间校验，失败直接回答；两种执行器路由一致；SQL 生成异常明确失败。
- 修改 `agent/state.py`：声明 request_reference_date、feedback_history、repair_request、repair_response、repair_outcome。
- 新增 `tests/test_feedback_loop.py`：外部模型和故障数据库用确定性替身，真实工作流、校验器、SQL 生成和 SQLite 执行不替换。
- 修改 `tests/test_workflow.py`：旧的“空数据原样执行三次”改为“空数据明确停止”，保留回归。

## Task 1: Red — reproduce missing model feedback

- [x] 为两套工作流参数化测试。测试模型首轮返回错误指标 ID，第二轮仅在收到反馈时返回正确的唯一候选；断言实际调用 payload 与真实 SQLite 结果。
- [x] 增加 SQL 执行故障场景：重复分组导致模拟目标引擎拒绝，模型去重后用真实 SQLite 成功执行；payload 必须携带上轮 SQL/计划/错误。
- [x] 加入无变化、STOP、非法响应、模型异常、预算、请求隔离、保护日期/筛选、无反馈正常、权限/空数据停止的测试。
- [x] 运行红测试，保存失败原因：没有第二轮模型调用或没有 feedback 字段，而非环境导入错误。

核心断言示例：

```python
assert len(model.repair_calls) == 1
payload = model.repair_calls[0]
assert payload['retry_feedback']['round'] == 1
assert payload['retry_feedback']['previous_sql'] == query.calls[0]
assert result['retry_count'] == 1
assert result['retry_action'] == 'ANSWER'
assert len(query.calls) == 2
```

## Task 2: Green — implement shared repair node and routing

- [x] 计划映射抽取为纯函数；请求日期在首轮确定，修复继续使用原值。
- [x] 实现修复响应 `{action: REVISE|STOP, reason: str, proposal: PLAN_SCHEMA|null}`，本地校验结构；保留安全失败原因。
- [x] 建立 feedback_history，快照深拷贝并限制为初轮失败＋一次修复失败；停止原因加入 trace，保留脱敏后的原始错误。
- [x] 保护指标定义、日期、过滤条件、维度集合、总计/派生要求和查询限制。比较有效计划与 SQL，拒绝无变化或删条件。
- [x] 更新两套工作流：`失败 → feedback_repair → 时间校验 → 计划校验 → SQL生成/校验 → 执行/结果校验`；所有不可恢复路径直接停止。
- [x] 跑定向测试并迭代至通过；新发现缺陷先追加红测试。

决策骨架：

```python
record = snapshot_failure(state)
if unrecoverable(record) or repair_budget_exhausted(state):
    return stop_with_history(record)
candidate = model.structured(input_text=repair_payload(record), schema=repair_schema)
if candidate['action'] == 'STOP' or not preserves_constraints(candidate):
    return stop_with_history(record)
return revised_plan_for_revalidation(candidate)
```

## Task 3: Verify and document

- [x] 完整 pytest 回归与改动文件静态检查；独立审查 M-1 相关 diff，不审查其他未提交改动。
- [x] 修复审查中的重要问题，重新运行覆盖测试及全量测试。
- [x] 文档记录实现范围、确切测试数量、真实模型未验证项；版本号保持 1.0.0。
- [x] 不自动提交、合并或发布；交付工作区变更及验证结果。
- [x] 真实模型验收：用户授权后限额执行两项受控修复，2 项通过；共 2 次调用、4,601 tokens，详见 M-1 实现记录。失败边界保持本地确定性测试覆盖，不扩大收费实验。

## Verification commands

项目虚拟环境包可由同版本系统 Python 读取：

```powershell
$env:PYTHONPATH = 'D:\py-project\agent-data\.venv\Lib\site-packages'
python -m pytest tests/test_feedback_loop.py -q -p no:cacheprovider
python -m pytest -q -p no:cacheprovider
git diff --check
```

基线：既有 53 项测试通过。沙箱临时目录可能无权限，测试可申请本地执行；依赖弃用警告单列，不当作功能失败。
