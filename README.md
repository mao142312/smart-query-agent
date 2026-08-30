# Smart Ask Data

> 项目知识与阶段成果采用 PARA 结构管理，入口见 [知识库/README.md](知识库/README.md)。

意图驱动、知识库 Grounding、逐轮 SQL 评分的智能问数服务。系统先用 AI 提取结构化意图并判断是否具备检索条件，再检索 Top N 企业知识、生成受知识约束的逻辑计划，最后经过 SQL 与结果评分后输出指标。

## 当前能力

- 指标公式、来源表、时间字段和强制过滤条件由知识库提供。
- AI 意图识别只提取业务线索，不能臆造正式指标、表名或字段名。
- 知识检索接收结构化条件，默认返回按匹配分排序的 Top 5 候选。
- 每轮 SQL 保存查询文本、返回行数、分项评分和失败原因。
- 计划、SQL 或结果低分时按流程图回退，达到重试上限后拒绝输出。
- 默认通过 Mock 知识库和内存 SQLite 运行，不依赖外部服务。
- 提供 CLI、HTTP API、健康检查、结构化日志及容器启动方式。
- 为 Qdrant、Trino 和真实 LLM 保留独立适配器边界。

## 本地运行

核心演示无需安装依赖：

```powershell
python main.py "昨天香港开户人数是多少？" --debug
python main.py --interactive
python -m unittest discover -s tests -v
```

## React 前端

问数控制台位于 `frontend/`，展示答案、综合可信度、知识/计划/SQL/结果分项评分，以及可展开的 SQL、执行路径与逐轮验证记录。

本地启动地址：

```text
前端：http://127.0.0.1:3000
后端：http://127.0.0.1:8000
```

前端默认连接 `http://127.0.0.1:8000`，也可以通过 `NEXT_PUBLIC_API_BASE_URL` 指定其他 API 地址。后端已允许本地 3000 和 5173 端口跨域访问。

安装完整服务依赖并启动 API：

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
uvicorn smart_ask_data.api:app --reload
```

接口：

```text
GET  /health
POST /v1/ask
GET  /docs
```

请求示例：

```json
{
  "question": "最近7天每天的开户人数",
  "debug": true
}
```

`debug=false` 时不会向调用方暴露 SQL 和内部执行轨迹。生产环境还应在 API 网关及查询层增加身份认证和行列级权限。

## Docker

```powershell
docker compose up --build
```

服务地址为 `http://localhost:8000`。

## 目录结构

```text
smart_ask_data/   应用配置、服务层、API、日志和依赖工厂
agent/            LangGraph 编排、状态及流程节点
tools/            知识库和查询引擎适配器
data/             可执行 Mock 指标知识库
config/           YAML 配置
prompts/          LLM 提示词
tests/            工作流及服务测试
```

## 配置

配置默认读取 `config/settings.yaml`，环境变量优先。完整变量见 `.env.example`。

切换 Trino：

```powershell
$env:SAD_QUERY_BACKEND = "trino"
$env:SAD_TRINO_HOST = "trino.example.com"
uvicorn smart_ask_data.api:app
```

### 启用 DeepSeek V4 Flash

项目默认模型为 `deepseek-v4-flash`，并开启思考模式。复制 `config/settings.local.example.yaml` 为 `config/settings.local.yaml`，然后填写密钥：

```yaml
llm:
  api_key: "你的 DeepSeek API Key"
```

`settings.local.yaml` 已被 Git 忽略，不会误提交密钥。`auto` 模式检测到配置文件中的密钥后启用真实调用，没有密钥时安全回退到规则规划：

```powershell
$env:SAD_LLM_BACKEND = "auto"
$env:SAD_LLM_MODEL = "deepseek-v4-flash"
$env:SAD_LLM_API_MODE = "chat_completions"
$env:SAD_LLM_BASE_URL = "https://api.deepseek.com"
$env:SAD_LLM_THINKING = "enabled"
python -m uvicorn smart_ask_data.api:app --host 127.0.0.1 --port 8000
```

模型参与意图识别、Grounded 语义规划和答案组织，但不能修改知识库指标口径，也不能绕过 SQL 与结果评分。模型回答未通过数值忠实性检查时，系统自动使用确定性回答。

## 可信度策略

综合可信度取知识检索、计划、SQL 和结果评分中的最低值，以避免严重问题被平均分掩盖：

- 意图不具备可检索条件：请求用户澄清，不检索知识库或执行 SQL。
- Top N 知识候选为空、低分或歧义过高：不执行 SQL。
- 规划器选择的指标不属于候选集合：不执行 SQL。
- SQL 使用非白名单表或遗漏强制条件：重新生成。
- 执行失败、空结果或指标为空：进入有界重试。
- 最终分数低于 `confidence_threshold`：返回 `unreliable`，不把结果作为可靠指标输出。

## 后续生产化里程碑

1. 接入真实指标知识库和向量/精确混合检索。
2. 接入企业认证、租户隔离及行列级权限。
3. 引入 SQL AST 校验和 Trino 查询资源限制。
4. 接入数据新鲜度、血缘、历史基线和权威报表对账。
5. 建立黄金问题集、离线评测和线上可观测面板。
