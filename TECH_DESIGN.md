# LakeQuery 技术设计文档

## 1. 技术栈总览

| 层级        | 组件                     | 版本要求 | PyPI 包名                     |
| ----------- | ------------------------ | -------- | ----------------------------- |
| Agent 编排  | LangGraph                | ≥0.2     | `langgraph`, `langchain-core` |
| LLM 调用    | LangChain OpenAI 兼容    | —        | `langchain-openai`            |
| 结构化输出  | Instructor + Pydantic v2 | ≥1.0     | `instructor`, `pydantic>=2.0` |
| 向量库      | Qdrant                   | ≥1.9     | `qdrant-client`               |
| 嵌入模型    | BGE-large-zh-v1.5        | —        | `sentence-transformers`       |
| SQL 解析    | sqlglot                  | ≥23.0    | `sqlglot`                     |
| 沙盒验证    | DuckDB                   | ≥0.10    | `duckdb`                      |
| Web 框架    | FastAPI + Uvicorn        | ≥0.110   | `fastapi`, `uvicorn`          |
| 前端        | Gradio                   | ≥4.0     | `gradio`                      |
| 可观测性    | Langfuse                 | ≥2.0     | `langfuse`                    |
| HMS 连接    | PyHive                   | ≥0.7     | `pyhive[hive]`                |
| Iceberg     | PyIceberg                | ≥0.6     | `pyiceberg`                   |
| Prompt 模板 | Jinja2                   | ≥3.0     | `jinja2`                      |
| 配置管理    | Pydantic Settings        | ≥2.0     | `pydantic-settings`           |

---

## 2. 项目目录结构

lakequery/
├── main.py                     # FastAPI 应用入口
├── config.py                   # 全局配置（Pydantic Settings）
├── models/                     # Pydantic 数据模型
│   ├── schema.py               # 元数据结构（Table / Column / Partition）
│   ├── query.py                # 请求/响应模型
│   └── state.py                # LangGraph 状态定义
├── agent/                      # Agent 核心
│   ├── graph.py                # LangGraph 状态机定义
│   ├── nodes.py                # 各节点实现（意图解析/SQL生成/校验等）
│   └── tools.py                # Agent 可调用的工具函数
├── catalog/                    # 元数据接入层（Catalog 适配器）
│   ├── base.py                 # CatalogAdapter 抽象基类
│   ├── hms.py                  # Hive Metastore 适配器
│   └── iceberg_rest.py         # Iceberg REST Catalog 适配器
├── rag/                        # 向量检索
│   ├── embedder.py             # 嵌入模型封装
│   ├── indexer.py              # 元数据向量化入库
│   └── retriever.py            # Schema RAG 检索
├── sql/                        # SQL 处理
│   ├── generator.py            # LLM SQL 生成（Instructor 结构化输出）
│   ├── validator.py            # sqlglot AST 校验
│   ├── sandbox.py              # DuckDB Dry-run 沙盒
│   └── transpiler.py           # sqlglot 方言转译
├── prompts/                    # Prompt 模板（Jinja2 + YAML）
│   ├── intent.yaml             # 意图解析 Prompt
│   ├── generate_sql.yaml       # SQL 生成 Prompt
│   └── fix_sql.yaml            # 纠错 Prompt
├── api/                        # FastAPI 路由
│   ├── routes.py               # REST 接口定义
│   └── deps.py                 # 依赖注入
├── ui/                         # Gradio 前端
│   └── app.py                  # Chatbot 界面
└── tests/
    ├── conftest.py             # 公共 fixture（mock LLM、DuckDB 连接、模拟元数据）
    ├── unit/
    │   ├── test_validator.py    # AST 校验单元测试
    │   ├── test_sandbox.py      # DuckDB 沙盒单元测试
    │   ├── test_transpiler.py   # 方言转译单元测试
    │   ├── test_retriever.py    # RAG 检索单元测试
    │   ├── test_state.py        # 状态模型单元测试
    │   └── test_security.py     # 安全规则单元测试
    ├── integration/
    │   ├── test_agent_graph.py  # LangGraph 端到端测试
    │   └── test_api.py          # FastAPI 接口测试
    └── fixtures/
        ├── sample_tables.json   # 模拟表元数据
        └── sample_queries.json  # 测试用例对

---

## 3. 核心数据结构

### 3.1 元数据模型（`models/schema.py`）

```python
from pydantic import BaseModel

class ColumnMeta(BaseModel):
    name: str                    # 列名
    data_type: str               # 数据类型，如 "STRING", "BIGINT"
    comment: str = ""            # 列注释
    is_partition_key: bool = False

class TableMeta(BaseModel):
    catalog: str                 # 所属 Catalog 名
    database: str                # 库名
    table_name: str              # 表名
    columns: list[ColumnMeta]
    partition_keys: list[str]    # 分区键列表，如 ["dt"]
    comment: str = ""            # 表注释
    storage_format: str = ""     # ORC / Parquet / Iceberg
    location: str = ""           # 存储路径

    @property
    def full_name(self) -> str:
        return f"{self.database}.{self.table_name}"

    def to_schema_text(self) -> str:
        """序列化为 LLM Prompt 中可读的文本"""
        cols = ", ".join(
            f"{c.name} {c.data_type}" + (f" -- {c.comment}" if c.comment else "")
            for c in self.columns
        )
        return f"{self.full_name}({cols}) [分区键: {','.join(self.partition_keys)}]"
```

### 3.2 LangGraph 状态（`models/state.py`）

```python
from typing import Literal
from pydantic import BaseModel

class AgentState(BaseModel):
    """LangGraph 状态机的全局状态，在节点间传递"""

    # 输入
    user_query: str                              # 用户原始自然语言
    target_dialect: str = "hive"                 # 目标引擎方言
    conversation_id: str = ""                    # 会话 ID（多轮对话追踪用）

    # 意图解析结果
    intent: dict | None = None                   # {time, dimensions, metrics, filters, sort}

    # Schema 检索结果
    candidate_tables: list[TableMeta] = []       # RAG 命中的候选表
    schema_context: str = ""                     # 拼接后喂给 LLM 的 Schema 文本

    # SQL 生成
    generated_sql: str = ""                      # LLM 生成的 ANSI SQL
    transpiled_sql: str = ""                     # sqlglot 转译后的目标方言 SQL

    # 校验
    validation_errors: list[str] = []            # 校验错误信息
    retry_count: int = 0                         # 当前重试次数
    max_retries: int = 3

    # 结果
    status: Literal["pending", "success", "failed"] = "pending"
    execution_result: list[dict] | None = None   # 查询结果行
    error_message: str = ""
```

> **Checkpointer 预留说明**：MVP 阶段 `AgentState` 仅在内存中生存。当后续需要支持多轮对话澄清（用户需求模糊时的追问）时，在 `graph.compile()` 时传入 `checkpointer` 参数即可启用状态持久化：
> ```python
> from langgraph.checkpoint.sqlite import SqliteSaver
> memory = SqliteSaver.from_conn_string("checkpoints.db")
> graph = workflow.compile(checkpointer=memory)
> ```
> 通过 `conversation_id` 字段关联同一会话的多轮状态，无需改动节点代码。

### 3.3 请求/响应模型（`models/query.py`）

```python
from pydantic import BaseModel

class QueryRequest(BaseModel):
    question: str                  # 用户自然语言问题
    dialect: str = "hive"          # 目标引擎: hive / spark / trino
    catalog: str = "default"       # 指定 Catalog
    execute: bool = False          # 是否实际执行 SQL（MVP默认只生成不执行）

class QueryResponse(BaseModel):
    sql: str                       # 生成的 SQL
    dialect: str                   # 实际使用的方言
    tables_used: list[str]         # 涉及的表
    validation_passed: bool        # 是否通过校验
    retry_count: int               # 重试次数
    execution_result: list[dict] | None = None
    error: str | None = None

class HealthResponse(BaseModel):
    status: str
    catalogs_connected: list[str]
    vector_store_count: int        # 向量库中的文档数
```

### 3.4 LLM 结构化输出模型（供 Instructor 使用）

```python
class ParsedIntent(BaseModel):
    """意图解析结构化输出"""
    time_range: str | None = None        # "2026-03"
    dimensions: list[str] = []           # ["province"]
    metrics: list[str] = []              # ["DAU日均"]
    filters: list[str] = []             # ["status='A'"]
    sort: str | None = None              # "avg_dau DESC"
    ambiguous: bool = False              # 是否需要澄清
    clarification_question: str = ""     # 若模糊，追问内容

class GeneratedSQL(BaseModel):
    """SQL 生成结构化输出"""
    sql: str                             # ANSI SQL
    reasoning: str                       # 生成推理过程（CoT）
    tables_used: list[str]               # 引用的表
    partition_filters: list[str]         # 使用的分区过滤条件
```

---

## 4. LangGraph 状态机设计

### 4.1 节点与边

```
                    ┌──────────────┐
                    │  START       │
                    └──────┬───────┘
                           ▼
                    ┌──────────────┐
                    │ parse_intent │  意图解析
                    └──────┬───────┘
                           │
                     ambiguous?
                    ┌──yes─┴──no──┐
                    ▼             ▼
            ┌──────────┐  ┌──────────────┐
            │ ask_user │  │ search_schema│  Schema RAG
            │ (澄清)   │  └──────┬───────┘
            └──────────┘         ▼
                          ┌──────────────┐
                          │ generate_sql │  LLM 生成 SQL
                          └──────┬───────┘
                                 ▼
                          ┌──────────────┐
                          │ validate_sql │  AST + DuckDB 校验
                          └──────┬───────┘
                                 │
                          passed? │
                     ┌──no───────┴───yes──┐
                     ▼                    ▼
              ┌─────────────┐     ┌──────────────┐
              │  fix_sql    │     │ transpile_sql│  方言转译
              │ (纠错+重试) │     └──────┬───────┘
              └──────┬──────┘            ▼
                     │            ┌──────────────┐
               retry < 3?        │  respond     │  返回结果
              ┌─yes──┴──no─┐     └──────────────┘
              ▼            ▼
        generate_sql    respond
        (重新生成)     (返回失败)
```

### 4.2 节点职责

| 节点            | 输入 State 字段                                 | 输出 State 字段                      | 核心逻辑                                        |
| --------------- | ----------------------------------------------- | ------------------------------------ | ----------------------------------------------- |
| `parse_intent`  | `user_query`                                    | `intent`, 可能设置 `ambiguous`       | Instructor 调 LLM →`ParsedIntent`               |
| `search_schema` | `intent`                                        | `candidate_tables`, `schema_context` | Qdrant 向量检索 Top-5 表，拼接 Schema 文本      |
| `generate_sql`  | `schema_context`, `intent`, `validation_errors` | `generated_sql`                      | Instructor 调 LLM →`GeneratedSQL`               |
| `validate_sql`  | `generated_sql`, `candidate_tables`             | `validation_errors`                  | sqlglot 解析 AST，检查表名/列名；DuckDB dry-run（见 4.4） |
| `fix_sql`       | `generated_sql`, `validation_errors`            | `retry_count += 1`                   | 将错误信息注入 Prompt，路由回 `generate_sql`    |
| `transpile_sql` | `generated_sql`, `target_dialect`               | `transpiled_sql`                     | sqlglot.transpile() 转译                        |
| `respond`       | 全部                                            | `status`, 最终输出                   | 组装 `QueryResponse`                            |

### 4.3 DuckDB 沙盒虚拟表机制

DuckDB Dry-run 的前提是本地 DuckDB 实例必须感知远端表的 Schema。做法是在元数据同步（`/api/v1/catalog/sync`）时，同步在 DuckDB 中创建对应的空视图：

```python
import duckdb

def sync_virtual_tables(conn: duckdb.DuckDBPyConnection, tables: list[TableMeta]):
    """根据 HMS/Iceberg 元数据，在 DuckDB 中创建同构空表供 Dry-run 使用"""
    for table in tables:
        # 先确保 schema 存在
        conn.execute(f"CREATE SCHEMA IF NOT EXISTS {table.database}")

        # 映射数据类型：HMS 类型 → DuckDB 类型
        type_map = {
            "STRING": "VARCHAR", "INT": "INTEGER", "BIGINT": "BIGINT",
            "DOUBLE": "DOUBLE", "FLOAT": "FLOAT", "BOOLEAN": "BOOLEAN",
            "TIMESTAMP": "TIMESTAMP", "DATE": "DATE", "DECIMAL": "DECIMAL",
        }
        col_defs = ", ".join(
            f"{c.name} {type_map.get(c.data_type.upper(), 'VARCHAR')}"
            for c in table.columns
        )
        # 用 CREATE OR REPLACE 保证幂等
        conn.execute(
            f"CREATE OR REPLACE TABLE {table.full_name} ({col_defs})"
        )
```

校验时，`validate_sql` 节点直接在这个有完整空表结构的 DuckDB 连接上执行：

```python
def duckdb_dry_run(conn: duckdb.DuckDBPyConnection, sql: str) -> list[str]:
    """在沙盒中尝试 EXPLAIN 生成的 SQL，捕获语法/类型错误"""
    errors = []
    try:
        conn.execute(f"EXPLAIN {sql}")
    except duckdb.Error as e:
        errors.append(f"DuckDB dry-run 失败: {e}")
    return errors
```

关键点：
- 虚拟表**只有结构没有数据**，DuckDB `EXPLAIN` 只做语法/类型检查，不需要真实数据
- 类型映射表 `type_map` 覆盖常见 Hive 类型；遇到未知类型退化为 `VARCHAR`（宁可漏报不误报）
- 每次 catalog sync 都会重建虚拟表，保证 Schema 与远端同步

### 4.4 Schema RAG 分层检索策略

单靠向量相似度检索容易在表数量多、字段语义相近时召回错误的表。采用**三级漏斗**提升准确率：

```
用户 query
    │
    ▼
[L1] 库级粗筛：根据 intent 中的业务域关键词，先过滤到 1-2 个 database
     （如 "DAU" → bi_dwd, "订单" → trade_dwd）
     实现：Qdrant payload filter, database 字段精确匹配
    │
    ▼
[L2] 表级向量检索：在筛选后的 database 内，用 embedding 相似度检索 Top-5 表
     实现：Qdrant search with filter
    │
    ▼
[L3] 列级重排序：用 LLM 对 Top-5 表的完整 Schema 做相关性打分，选出最终 Top-3
     实现：一次轻量 LLM 调用，输入 = intent + 5 张表 Schema，输出 = 排序后的表名列表
```

```python
def search_schema(state: AgentState, qdrant: QdrantClient, embedder) -> AgentState:
    query_vec = embedder.encode(state.user_query)

    # L1: 库级粗筛 —— 若 intent 中能识别出业务域，加 filter
    db_filter = None
    if state.intent and state.intent.get("database_hint"):
        db_filter = models.Filter(
            must=[models.FieldCondition(
                key="database", match=models.MatchValue(value=state.intent["database_hint"])
            )]
        )

    # L2: 表级向量检索
    results = qdrant.search(
        collection_name="table_schemas",
        query_vector=query_vec,
        query_filter=db_filter,
        limit=5,
    )
    candidate_tables = [load_table_meta(r.payload) for r in results]

    # L3: 列级重排序（可选，MVP 阶段可跳过，直接用 Top-5）
    # reranked = llm_rerank(state.intent, candidate_tables)

    state.candidate_tables = candidate_tables
    state.schema_context = "\n".join(t.to_schema_text() for t in candidate_tables)
    return state
```

### 4.5 Graph 定义伪代码

```python
from langgraph.graph import StateGraph, END

workflow = StateGraph(AgentState)

# 添加节点
workflow.add_node("parse_intent", parse_intent_node)
workflow.add_node("search_schema", search_schema_node)
workflow.add_node("generate_sql", generate_sql_node)
workflow.add_node("validate_sql", validate_sql_node)
workflow.add_node("fix_sql", fix_sql_node)
workflow.add_node("transpile_sql", transpile_sql_node)
workflow.add_node("respond", respond_node)

# 定义边
workflow.set_entry_point("parse_intent")
workflow.add_conditional_edges("parse_intent", route_after_intent,
    {"ambiguous": END, "clear": "search_schema"})  # 模糊则返回追问
workflow.add_edge("search_schema", "generate_sql")
workflow.add_edge("generate_sql", "validate_sql")
workflow.add_conditional_edges("validate_sql", route_after_validation,
    {"passed": "transpile_sql", "failed": "fix_sql"})
workflow.add_conditional_edges("fix_sql", route_after_fix,
    {"retry": "generate_sql", "give_up": "respond"})
workflow.add_edge("transpile_sql", "respond")
workflow.add_edge("respond", END)

graph = workflow.compile()
```

---

## 5. API 接口设计

### 5.1 REST API（FastAPI）

#### 核心查询接口

```
POST /api/v1/query
```

请求体：

```json
{
  "question": "查一下2026年3月各省份的DAU日均值，按降序排列",
  "dialect": "hive",
  "catalog": "default",
  "execute": false
}
```

响应体（200）：

```json
{
  "sql": "SELECT province, AVG(dau) AS avg_dau FROM bi_dwd.dau_daily WHERE dt BETWEEN '20260301' AND '20260331' GROUP BY province ORDER BY avg_dau DESC",
  "dialect": "hive",
  "tables_used": ["bi_dwd.dau_daily"],
  "validation_passed": true,
  "retry_count": 0,
  "execution_result": null,
  "error": null
}
```

响应体（200，需要澄清）：

```json
{
  "sql": "",
  "dialect": "hive",
  "tables_used": [],
  "validation_passed": false,
  "retry_count": 0,
  "execution_result": null,
  "error": "问题不够明确：请问"活跃用户"是指日活(DAU)还是月活(MAU)？"
}
```

#### 元数据管理

```
POST   /api/v1/catalog/sync          # 触发元数据同步（拉取 → 向量化）
GET    /api/v1/catalog/tables         # 列出已索引的表
GET    /api/v1/catalog/tables/{name}  # 查看单张表的 Schema
```

`POST /api/v1/catalog/sync` 请求体：

```json
{
  "catalog_type": "hms",
  "connection": {
    "host": "hive-metastore.internal",
    "port": 9083
  },
  "databases": ["bi_dwd", "bi_dws"]
}
```

响应体（200）：

```json
{
  "tables_synced": 42,
  "vectors_upserted": 42,
  "duration_seconds": 3.2
}
```

#### 黄金查询管理（第二期）

```
POST   /api/v1/golden-queries         # 确认保存一条黄金查询
GET    /api/v1/golden-queries          # 列出所有黄金查询
DELETE /api/v1/golden-queries/{id}     # 删除
```

#### 健康检查

```
GET /api/v1/health
```

```json
{
  "status": "ok",
  "catalogs_connected": ["hms_default"],
  "vector_store_count": 42
}
```

### 5.2 LLM API 调用约定

所有 LLM 调用统一走 OpenAI 兼容接口（DeepSeek / Qwen 均支持）：

```python
import instructor
from openai import OpenAI

client = instructor.from_openai(
    OpenAI(base_url="https://api.deepseek.com", api_key=settings.llm_api_key)
)

# 意图解析
intent = client.chat.completions.create(
    model="deepseek-chat",
    response_model=ParsedIntent,
    messages=[
        {"role": "system", "content": rendered_system_prompt},
        {"role": "user", "content": user_query},
    ],
    temperature=0,
)
```

### 5.3 向量库调用约定

```python
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct

# 初始化（本地模式，零配置）
qdrant = QdrantClient(path="./qdrant_data")

# 创建集合
qdrant.create_collection(
    collection_name="table_schemas",
    vectors_config=VectorParams(size=1024, distance=Distance.COSINE),
)

# 入库
qdrant.upsert(collection_name="table_schemas", points=[
    PointStruct(id=hash(table.full_name), vector=embedding, payload={
        "full_name": table.full_name,
        "schema_text": table.to_schema_text(),
        "database": table.database,
        "partition_keys": table.partition_keys,
    })
])

# 检索
results = qdrant.search(
    collection_name="table_schemas",
    query_vector=query_embedding,
    limit=5,
)
```

---

## 6. 配置管理

### 6.1 全局配置（`config.py`）

```python
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    # LLM
    llm_provider: str = "deepseek"              # deepseek / qwen
    llm_api_key: str                             # 必填
    llm_base_url: str = "https://api.deepseek.com"
    llm_model: str = "deepseek-chat"
    llm_temperature: float = 0.0

    # 向量库
    qdrant_path: str = "./qdrant_data"           # 本地模式路径
    qdrant_url: str | None = None                # 远程模式 URL（设置后忽略 path）
    embedding_model: str = "BAAI/bge-large-zh-v1.5"
    rag_top_k: int = 5

    # 沙盒
    duckdb_memory_limit: str = "256MB"
    max_retry: int = 3

    # HMS
    hms_host: str = "localhost"
    hms_port: int = 9083

    # Langfuse
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_host: str = "http://localhost:3000"

    # Server
    server_host: str = "0.0.0.0"
    server_port: int = 8000

    class Config:
        env_file = ".env"
        env_prefix = "LQ_"                       # 环境变量前缀: LQ_LLM_API_KEY 等
```

### 6.2 Prompt 管理策略

**MVP 阶段**：所有 Prompt 以 Python 常量形式写死在 `agent/prompts.py` 中。理由：
- 减少间接层，AI 辅助编码时能直接看到完整上下文
- 调试时改一处即生效，不用在 YAML 和 Python 之间跳转
- 核心链路跑通后再重构抽离

```python
# agent/prompts.py —— MVP 阶段的 Prompt 常量

SYSTEM_GENERATE_SQL = """
你是一个专业的 SQL 生成助手。根据用户的自然语言需求和提供的数据库 Schema，生成标准 ANSI SQL。

规则：
1. 只使用提供的表和列，不要编造不存在的表或字段
2. 必须包含分区键过滤条件（如 dt），避免全表扫描
3. 生成标准 ANSI SQL，不要使用特定引擎的函数
4. 只生成 SELECT 语句，禁止 INSERT/UPDATE/DELETE/DROP/CREATE

可用 Schema：
{schema_context}
"""

USER_GENERATE_SQL = """
用户需求：{user_query}
"""

USER_FIX_SQL = """
用户需求：{user_query}

上一次生成的 SQL：
{generated_sql}

存在以下错误，请修正：
{validation_errors}
"""
```

**生产阶段迁移**：当 Prompt 稳定后，迁移到 Jinja2 + YAML 模板（`prompts/` 目录），实现版本管理和 A/B 测试。迁移时只需将常量替换为模板渲染调用，节点代码不变。

---

## 7. 安全设计

| 防护点              | 机制         | 实现方式                                                     |
| ------------------- | ------------ | ------------------------------------------------------------ |
| SQL 注入/破坏性语句 | AST 白名单   | sqlglot 解析后检查 AST 根节点只允许 `SELECT`；拒绝 `INSERT/UPDATE/DELETE/DROP/CREATE/ALTER` |
| 全表扫描            | 分区键检查   | 解析 WHERE 子句，验证包含 `TableMeta.partition_keys` 中的至少一个字段 |
| DuckDB 沙盒逃逸     | 禁用外部访问 | `SET enable_external_access = false; SET enable_object_cache = false;` |
| LLM 输出不可控      | 结构化输出   | Instructor 强制返回 Pydantic 模型，非法字段直接报错          |
| API 滥用            | 速率限制     | FastAPI middleware，单 IP 限 60 次/分钟                      |

---

## 8. 依赖清单（`requirements.txt`）

```
# Agent & LLM
langgraph>=0.2
langchain-core>=0.2
langchain-openai>=0.1
instructor>=1.0
pydantic>=2.0
pydantic-settings>=2.0

# Vector Store & Embedding
qdrant-client>=1.9
sentence-transformers>=2.2

# SQL Processing
sqlglot>=23.0
duckdb>=0.10

# Web
fastapi>=0.110
uvicorn>=0.29
gradio>=4.0

# Metadata
pyhive[hive]>=0.7
pyiceberg>=0.6

# Observability
langfuse>=2.0

# Template
jinja2>=3.0
pyyaml>=6.0

# Dev & Test
pytest>=8.0
pytest-asyncio>=0.23  # 异步测试支持
httpx>=0.27           # FastAPI TestClient
faker>=24.0           # 生成模拟元数据
```

---

## 9. 测试规范（TDD）

### 9.1 原则

**所有核心函数必须先写 Pytest 单元测试，再实现功能代码**。这是该项目质量的底线——Agent 系统的中间环节（AST 解析、状态机路由、类型映射）极难通过手动测试覆盖。

### 9.2 测试目录结构

```
tests/
├── conftest.py                  # 公共 fixture（mock LLM、mock Qdrant、DuckDB 连接）
├── unit/
│   ├── test_validator.py        # sqlglot AST 校验：合法/非法 SQL、DDL 拦截、表名验证
│   ├── test_sandbox.py          # DuckDB dry-run：虚拟表创建、类型映射、EXPLAIN 报错捕获
│   ├── test_transpiler.py       # 方言转译：ANSI→Hive/Spark/Trino 的函数/语法差异
│   ├── test_retriever.py        # RAG 检索：分层过滤逻辑、payload filter 构建
│   ├── test_state.py            # AgentState 序列化/反序列化、字段默认值
│   └── test_security.py         # 安全规则：DDL 拦截、分区键检查、沙盒配置
├── integration/
│   ├── test_agent_graph.py      # LangGraph 端到端：happy path + 纠错循环 + 超限失败
│   └── test_api.py              # FastAPI 路由：请求/响应格式、错误码
└── fixtures/
    ├── sample_tables.json       # 模拟 TableMeta 数据（3-5 张典型表）
    └── sample_queries.json      # (自然语言, 期望SQL) 测试对
```

### 9.3 关键 Fixture

```python
# tests/conftest.py
import pytest
import duckdb
from lakequery.models.schema import TableMeta, ColumnMeta

@pytest.fixture
def sample_tables() -> list[TableMeta]:
    """3 张典型表的元数据，覆盖：分区表、无分区表、多种数据类型"""
    return [
        TableMeta(
            catalog="default", database="bi_dwd", table_name="dau_daily",
            columns=[
                ColumnMeta(name="dt", data_type="STRING", is_partition_key=True),
                ColumnMeta(name="province", data_type="STRING"),
                ColumnMeta(name="dau", data_type="BIGINT"),
            ],
            partition_keys=["dt"],
        ),
        # ... 更多表
    ]

@pytest.fixture
def duckdb_conn(sample_tables) -> duckdb.DuckDBPyConnection:
    """内存 DuckDB 连接，已预建虚拟表"""
    conn = duckdb.connect(":memory:")
    conn.execute("SET enable_external_access = false")
    from lakequery.sql.sandbox import sync_virtual_tables
    sync_virtual_tables(conn, sample_tables)
    return conn

@pytest.fixture
def mock_llm():
    """Mock LLM 客户端，返回预设结构化输出，不消耗 API Token"""
    # 使用 unittest.mock 或 pytest-mock
    ...
```

### 9.4 测试优先级

| 优先级 | 模块 | 必须覆盖的场景 |
|--------|------|----------------|
| P0 | `test_validator.py` | SELECT 通过 / INSERT 拦截 / 不存在的表名报错 / 不存在的列名报错 |
| P0 | `test_sandbox.py` | 合法 SQL EXPLAIN 通过 / 语法错误被捕获 / 类型不匹配被捕获 |
| P0 | `test_agent_graph.py` | 正常路径一次通过 / 校验失败触发重试 / 重试 3 次后返回失败 |
| P1 | `test_transpiler.py` | ANSI→Hive 日期函数转换 / LIMIT→Hive 兼容 |
| P1 | `test_security.py` | DDL 全部拦截 / 缺分区键被阻断 / DuckDB 外部访问已禁用 |
| P2 | `test_api.py` | 200 正常响应 / 422 参数校验 / 澄清场景响应格式 |

---

## 10. 部署架构（MVP 单机 Docker）

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY lakequery/ ./lakequery/
EXPOSE 8000 7860
CMD ["sh", "-c", "uvicorn lakequery.main:app --host 0.0.0.0 --port 8000 & python -m lakequery.ui.app"]
```

```
┌─────────────────────────────────┐
│         Docker Container        │
│                                 │
│  :8000  FastAPI REST API        │
│  :7860  Gradio Web UI           │
│                                 │
│  ./qdrant_data/  (向量持久化)    │
│  ./prompts/      (Prompt模板)    │
│  .env            (配置)          │
└────────────┬────────────────────┘
             │ Thrift / REST
             ▼
    HMS / Iceberg Catalog (外部)
```
