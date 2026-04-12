# LakeQuery 上线前稳定性审查报告

**审查范围**：lakequery + tests 全量代码（M1-M4），对标 AGENTS.md + TECH_DESIGN.md  
**审查时间**：2026-04-11  
**代码状态**：77 测试全绿，即将接入 Gradio UI

---

## 一、本地资源与存储管理 (Resource & Storage Optimization)

### 1.1 Qdrant 持久化路径 — 存在隐性风险

| 配置项       | 当前值                             | 风险                                       |
| ------------ | ---------------------------------- | ------------------------------------------ |
| `qdrant_url` | `http://localhost:6333`            | 外部 Qdrant 服务，数据路径由 Qdrant 侧控制 |
| Collection   | `table_schemas` + `golden_queries` | 无自动创建逻辑（见下方 **R1**）            |

**R1 (P0)** — **Qdrant collection 不存在时 Agent 管道直接崩溃**

routes.py 中 `catalog/sync` 和 `golden-queries` 端点直接调用 `client.upsert()`，但**没有任何地方确保 `table_schemas` 和 `golden_queries` 两个 collection 已被创建**。生产环境中如果 Qdrant 是全新实例（或者容器重建），首次请求必然触发 `qdrant_client.http.exceptions.UnexpectedResponse: Collection not found`。

- **触发场景**：首次部署、Qdrant 容器重启后丢失内存数据
- **影响链路**：`/api/v1/catalog/sync` → `index_tables()` → `client.upsert()` → 500；Agent 管道中 `search_schema_node` / `check_golden_node` → 500
- **建议**：在 main.py 的 FastAPI `lifespan` 事件中添加 `ensure_collections()` 初始化逻辑，使用 `recreate_collection(..., on_disk_payload=True)` 或条件检查 `get_collection` → `create_collection`。

---

**R2 (P1)** — **DuckDB 沙盒 `:memory:` 模式下每次校验创建/销毁连接的开销**

sandbox.py 中 `SandboxManager` 每次调用都会：
1. `duckdb.connect(":memory:")`
2. 安全配置
3. `sync_virtual_tables()` — 对所有 candidate_tables 执行 `CREATE SCHEMA IF NOT EXISTS` + `CREATE OR REPLACE TABLE`
4. `EXPLAIN`
5. `conn.close()`

在纠错循环中（最多 3 轮），每轮都完整重建一遍虚拟表。当 `candidate_tables` 数量增长到数十张（HMS 同步整个 database 后），这是 **O(retry * tables)** 的重复 DDL 开销。

- **触发场景**：用户查询命中 20+ 表，且 LLM 连续 3 轮生成错误 SQL
- **建议**：将 DuckDB conn 挂载到 `AgentState`（或通过图上下文传递），在 `search_schema_node` 完成后创建一次并复用至 `respond_node` 后销毁。注意线程安全——DuckDB 的 `:memory:` 连接本身不是线程安全的，需确保同一请求内串行使用。

---

**R3 (P2)** — **`SentenceTransformer` 模型缓存路径未配置**

embedder.py 中 `SentenceTransformer(settings.embedding_model)` 首次加载时会下载到 `~/.cache/torch/sentence_transformers/`（默认路径）。在 Windows 上即 `C:\Users\<user>\.cache\`。

- 模型文件约 1.3 GB（bge-large-zh-v1.5）
- 服务器部署时可能需要指定缓存到数据盘
- **建议**：在 config.py 中增加 `embedding_cache_dir` 配置项，传递给 `SentenceTransformer(model_name, cache_folder=...)`。

---

**R4 (P2)** — **`golden_queries` collection 无限增长无清理策略**

indexer.py `save_golden_query` 每次都用 `uuid.uuid4().hex` 生成新的点 ID，**相同问题重复提交会产生重复记录**。长期运行后 collection 膨胀可能导致检索变慢。

- **建议**：改用 `hashlib` 对 `question` 做确定性 hash 作为点 ID（与 `_table_id` 同策略），实现幂等 upsert。

---

## 二、端到端异常穿透 (End-to-End Exception Flow)

### 2.1 节点层异常处理 — 较之前大幅改善 ✅

查验所有 8 个节点函数（nodes.py），每个都已包裹 `try-except`，捕获后写入 `validation_errors` 或 `status=failed`，符合 AGENTS.md 规范。

### 2.2 发现的问题

**E1 (P0)** — **`/api/v1/query` 路由缺少全局异常保护**

routes.py 中 `query()` 函数直接 `await graph.ainvoke(initial_state)`，**没有 try-except**。虽然节点层已做防御，但以下场景仍会导致未捕获异常穿透为 HTTP 500：

| 异常源                                 | 触发条件                                                     | 穿透路径                                                     |
| -------------------------------------- | ------------------------------------------------------------ | ------------------------------------------------------------ |
| LangGraph 内部错误                     | 图编译异常、节点函数签名不匹配                               | `graph.ainvoke()` 抛出 `GraphRecursionError` 或 `InvalidUpdateError` |
| Pydantic 序列化错误                    | `result` dict 中字段类型与 `QueryResponse` 不匹配            | `QueryResponse(...)` 构造函数抛出 `ValidationError`          |
| `result.get("candidate_tables_names")` | `candidate_tables_names` 键不存在于 result dict 中，会返回 `[]` 但... | **实际上这里有个 bug**：State 中字段叫 `candidate_tables`（`list[TableMeta]`对象），没有 `candidate_tables_names` 字段。`result.get("candidate_tables_names", [])` 永远返回 `[]`，`tables_used` 永远为空列表。 |

- **建议**：
  1. 在 `query()` 外层加 `try-except Exception`，异常时返回 `QueryResponse(error=str(e), ...)`
  2. 修复 `tables_used` 的取值逻辑：`[t.full_name for t in result.get("candidate_tables", [])]` 或在 `respond_node` 中组装好 `tables_used` 字段

---

**E2 (P1)** — **`/api/v1/catalog/sync` 中 HMS 连接超时无保护**

routes.py 中 `await asyncio.to_thread(client.fetch_database_schema, request.database)` 将 HMS 调用推入线程池，但 `HMSClient.fetch_database_schema` 中 `hive.connect()` 没有 `timeout` 参数。

hms.py：
```python
conn = hive.connect(host=self.host, port=self.port, database=database)
```

如果 Hive Metastore 不可达，`pyhive.hive.connect()` 会**阻塞线程池线程**（默认 TCP 超时可能长达 2 分钟），在 `asyncio.to_thread` 下不会阻塞事件循环，但会耗尽 uvicorn 的线程池 workers。外层没有 try-except，最终会返回未处理的 `TTransportException`。

- **建议**：给 `hive.connect()` 配置 `configuration={"hive.server2.session.timeout.seconds": "30"}`，并在路由层捕获 `Exception` 返回 400/503。

---

**E3 (P1)** — **`search_schema_node` 的 local catalog 兜底逻辑不设置 `candidate_tables_names`**

nodes.py 中当 Qdrant 失败时的兜底分支 `from lakequery.catalog import load_local_tables` 是合理的。但 `load_local_tables()` 加载的表是固定的 3 张硬编码表（local_tables.json）。如果用户查询涉及的表不在这 3 张中，后续 `validate_sql` 会报 "未知的表"，但错误信息不会指明"由 Qdrant 故障降级为本地 catalog"。建议在 `validation_errors` 或日志中标注降级来源。

---

**E4 (P1)** — **`check_golden_node` 在 Qdrant collection 不存在时返回空 dict，但图的路由逻辑依赖 `is_golden_hit`**

nodes.py 中 `check_golden_node` 异常时返回 `{}`，不设置 `is_golden_hit`。然后 graph.py 中的路由：

```python
def route_after_golden(state: AgentState) -> str:
    if state.is_golden_hit:
        return "validate_sql"
    return "search_schema"
```

由于 `AgentState.is_golden_hit` 默认值为 `False`，当异常时返回的空 dict 不覆盖它，路由走 `search_schema` — **行为正确**。但这是一个"巧合正确"而非"显式正确"。如果未来有人把默认值改为 `None`，路由就会出错。

- **建议**：异常分支显式返回 `{"is_golden_hit": False}`。

---

**E5 (P2)** — **FastAPI 缺少全局异常处理器**

main.py 只有两行，没有注册 `@app.exception_handler(Exception)` 或 `@app.exception_handler(RequestValidationError)`。

当前默认行为：Python 异常 → FastAPI 自动返回 `{"detail": "Internal Server Error"}`（HTTP 500），日志中输出完整 traceback。这对于 Gradio UI 端来说还能接受（会展示 "HTTP 500"），但：
1. 敏感的内部堆栈信息可能通过 debug 模式泄露
2. 没有统一的错误响应格式（500 返回 `{detail}` 而正常错误返回 `QueryResponse.error`）

- **建议**：添加全局 exception handler，统一返回 JSON 格式 `{"error": "..."}` 并记录日志。

---

## 三、并发重入与黄金查询边界 (Concurrency & Edge Cases)

### 3.1 黄金查询相似度阈值分析

**G1 (P0)** — **黄金查询匹配只比较语义相似度，完全忽略时间/数值条件差异**

retriever.py 中：

```python
async def search_golden_query(
    client, embedder, question, threshold=0.85
) -> str | None:
    query_vector = embedder.encode(question)
    results = await client.query_points(
        collection_name=settings.qdrant_golden_collection,
        query=query_vector, limit=1, score_threshold=threshold,
    )
    if results.points:
        return results.points[0].payload["sql"]
    return None
```

**致命场景**：

| 黄金查询（已保存）      | 用户新请求                | 语义相似度 | 实际差异         |
| ----------------------- | ------------------------- | ---------- | ---------------- |
| "查下**昨天**各省的DAU" | "查下**上个月**各省的DAU" | >0.95      | 时间条件完全不同 |
| "查下**北京**的订单量"  | "查下**上海**的订单量"    | >0.93      | 地域过滤条件不同 |
| "2026-03 的 GMV"        | "2026-01 的 GMV"          | >0.90      | 月份不同         |

BGE-large-zh-v1.5 是语义模型，对句子结构和主题敏感，但对时间/数值/地名等**参数化差异不敏感**。0.85 的阈值在上述场景中几乎必定被命中，返回的历史 SQL 包含硬编码的旧日期条件（如 `WHERE dt = '20260409'`），**直接跳过 LLM 生成和校验** → 返回过期/错误的数据。

这是目前代码库中**风险最高的逻辑缺陷**。通过 graph.py，黄金命中后直接走 `validate_sql` → `transpile_sql` → `respond`，完全绕过意图解析和 Schema RAG。

**建议方案（选其一或组合）**：
1. **阈值提高到 0.95+** 并在 payload 中存储结构化意图（`ParsedIntent`），命中后对比 `time_range`、`filters` 等关键字段是否一致
2. **黄金查询只存储 SQL 模板化版本**：将时间条件替换为占位符 `{dt_filter}`，命中后由 LLM 做参数回填
3. **最保守方案**：黄金查询命中后 **不跳过 generate_sql**，而是作为 few-shot example 注入 Prompt，让 LLM 在参考历史 SQL 的基础上生成新 SQL

---

**G2 (P1)** — **`threshold` 硬编码在函数签名中，不可配置**

retriever.py `threshold: float = 0.85` 是函数默认参数，调用方 `check_golden_node` 也没有从 `settings` 读取。上线后如需调整阈值，必须改代码重新部署。

- **建议**：在 config.py 的 `Settings` 中增加 `golden_query_threshold: float = 0.85`，由 `check_golden_node` 传入。

---

**G3 (P1)** — **`embedder.encode()` 是同步阻塞调用，在 async 节点中未用 `to_thread` 包裹**

nodes.py 中 `check_golden_node` 和 nodes.py 中 `search_schema_node` 都是 `async def`，但内部调用：
```python
embedder = get_embedder()
# ...
query_vector = embedder.encode(query)  # 这是 SentenceTransformer.encode()，CPU 密集 + 同步阻塞
```

`SentenceTransformer.encode()` 是 PyTorch 推理调用，在 CPU 上可能耗时 50-200ms。由于它在 async 函数中同步执行，会**阻塞 uvicorn 的事件循环**，影响其他并发请求的响应延迟。

调用链路：
- `search_schema_node` → `search_tables()` → `embedder.encode()` (阻塞)
- `check_golden_node` → `search_golden_query()` → `embedder.encode()` (阻塞)

- **建议**：将 `embedder.encode()` 用 `await asyncio.to_thread(embedder.encode, query)` 包裹，或将 retriever 层的 encode 调用统一改为异步。

---

**G4 (P1)** — **`get_llm_client()` 每次调用创建新的 `AsyncOpenAI` 实例**

nodes.py：

```python
def get_llm_client():
    return instructor.from_openai(
        AsyncOpenAI(base_url=..., api_key=...),
    )
```

**没有 `@lru_cache`**。每个节点调用都会创建新的 `AsyncOpenAI` 实例及其内部的 `httpx.AsyncClient` 连接池。一次完整查询中 `parse_intent_node` + `generate_sql_node`（可能多次）= 2-5 次实例化。每次新建的 httpx client 无法复用 TCP 连接。

- **触发影响**：TCP 连接复用率低、TLS 握手重复开销、可能触发 API 端的速率限制（每个 client 独立计数）
- **建议**：加 `@functools.lru_cache(maxsize=1)`（与 `get_qdrant_client` / `get_embedder` 保持一致）

---

**G5 (P2)** — **`graph = build_graph().compile()` 模块级单例在 uvicorn reload 模式下存在问题**

graph.py 在模块导入时编译图。`uvicorn --reload` 下每次文件变更会重新导入，问题不大。但如果后续需要支持 per-request 配置（如不同 `max_retries`），模块级单例无法满足。

- **影响**：目前可接受，M5+ 需重构为工厂模式。

---

## 四、总结 — 问题统计与修复优先级

| 等级   | 编号 | 问题概述                                              | 影响范围          |
| ------ | ---- | ----------------------------------------------------- | ----------------- |
| **P0** | R1   | Qdrant collection 不存在时 Agent/API 500              | 首次部署必现      |
| **P0** | E1   | `/query` 路由无 try-except + `tables_used` 永远为空   | 每次请求          |
| **P0** | G1   | 黄金查询语义命中忽略时间/条件差异，返回过期 SQL       | 时间条件不同时    |
| **P1** | R2   | DuckDB 沙盒连接每次重建，纠错循环开销线性增长         | 重试场景          |
| **P1** | E2   | HMS 连接无超时，阻塞线程池                            | HMS 不可达时      |
| **P1** | E3   | Local catalog 降级无明确标识                          | Qdrant 故障时     |
| **P1** | E4   | `check_golden_node` 异常时 `is_golden_hit` 依赖默认值 | Qdrant 故障       |
| **P1** | G2   | 黄金查询阈值硬编码                                    | 调参需改代码      |
| **P1** | G3   | `embedder.encode()` 阻塞事件循环                      | 每次请求 50-200ms |
| **P1** | G4   | `get_llm_client()` 每次新建连接池                     | 每次请求          |
| **P2** | R3   | Embedding 模型缓存路径未配置                          | 部署环境          |
| **P2** | R4   | 黄金查询重复提交产生重复记录                          | 长期运行          |
| **P2** | E5   | FastAPI 无全局异常处理器                              | 非预期异常        |
| **P2** | G5   | Graph 模块级单例不支持 per-request 配置               | 后续扩展          |

### 建议修复路线

```
┌─── 发版阻塞（上线前必须修复）──────────────────────────────────┐
│ R1. main.py lifespan 中 ensure_collections()                   │
│ E1. /query 路由加 try-except + 修复 tables_used 取值           │
│ G1. 黄金查询增加意图对比 / 提高阈值 / 改为 few-shot 注入      │
│ G4. get_llm_client() 加 @lru_cache(maxsize=1)                 │
└────────────────────────────────────────────────────────────────┘
            ↓
┌─── 上线首周修复 ──────────────────────────────────────────────┐
│ G3. embedder.encode() 用 asyncio.to_thread 包裹               │
│ G2. golden_query_threshold 移入 Settings                      │
│ E2. hive.connect 加 timeout + 路由层 try-except               │
│ E4. check_golden_node 异常分支显式返回 is_golden_hit=False    │
│ R2. DuckDB conn 复用至请求结束                                │
└────────────────────────────────────────────────────────────────┘
```

**最高优先级行动项**：**G1（黄金查询条件盲命中）** 是功能正确性缺陷——用户问"上个月的 GMV"却拿到"昨天的 GMV" SQL，属于静默返回错误数据，比 500 报错更危险。建议上线前至少将阈值提到 0.95 并增加 `time_range` 一致性校验。