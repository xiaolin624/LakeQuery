# LakeQuery 全局代码审计报告

**审计范围**：lakequery 全部模块 + tests 全部文件，对标 AGENTS.md + TECH_DESIGN.md  
**审计时间**：2026-04-11  
**代码版本**：M1+M2 完成，39 个 TDD 测试全部通过

---

## 一、架构边界与防御性编程 (Architecture & Defense)

### 1.1 依赖方向 — 总体合规 ✅

| 模块                | 实际 import 方向                      | 规范 | 结论           |
| ------------------- | ------------------------------------- | ---- | -------------- |
| `sql/validator.py`  | → `models.schema`                     | ✅    | 无反向依赖     |
| `sql/sandbox.py`    | → `models.schema`                     | ✅    | 无反向依赖     |
| `sql/transpiler.py` | 仅 `sqlglot`                          | ✅    | 纯工具函数     |
| `rag/retriever.py`  | → `config`, `models.schema`           | ✅    | 无反向依赖     |
| `rag/embedder.py`   | → `config`                            | ✅    | 无反向依赖     |
| `rag/indexer.py`    | → `config`, `models.schema`           | ✅    | 无反向依赖     |
| `agent/nodes.py`    | → `rag/`, `sql/`, `config`, `models/` | ✅    | 符合编排层定位 |
| `agent/graph.py`    | → `agent/nodes`, `models/`            | ✅    | 只做图结构定义 |

**结论**：层级依赖 `agent → rag, sql, catalog → models, config` 严格遵守，无反向依赖。

---

### 1.2 发现的问题

| #      | 等级   | 问题                                             | 文件         | 详情                                                         |
| ------ | ------ | ------------------------------------------------ | ------------ | ------------------------------------------------------------ |
| **A1** | **P0** | DuckDB 沙盒未集成到 Agent 管道                   | nodes.py     | `validate_sql_node` 只调用了 `validate_sql()`（AST 校验），**完全没有调用 `duckdb_dry_run()`**。TECH_DESIGN §4.2 明确要求 validate_sql 节点"sqlglot 解析 AST + DuckDB dry-run"。沙盒模块写好了、测试也过了，但**根本没接入流水线**，等于形同虚设。 |
| **A2** | **P0** | DuckDB 沙盒缺少 `enable_external_access = false` | sandbox.py   | 测试 fixture `duckdb_conn` 正确设置了安全限制（conftest.py），但**生产代码 sandbox.py 中没有任何安全初始化**。一旦 M3 接入真实请求，DuckDB 可以通过 `read_csv_auto('/etc/passwd')` 等函数读取文件系统。AGENTS.md 明确要求："DuckDB 沙盒初始化时**必须**执行 `SET enable_external_access = false`"。 |
| **A3** | **P0** | `sync_virtual_tables` 存在 SQL 注入风险          | sandbox.py   | 表名/库名/列名通过 f-string 直接拼入 DDL，无引号转义。若元数据源（HMS/Iceberg）被投毒注入恶意标识符（如 `foo; DROP TABLE bar`），会导致任意 SQL 执行。应使用 `sqlglot` 的 `exp.to_identifier(name, quoted=True)` 或 DuckDB 参数化。 |
| **A4** | **P1** | AST 校验未拦截 `SELECT ... INTO`                 | validator.py | sqlglot 将 `SELECT ... INTO new_table FROM ...` 解析为 `exp.Select`（带 `Into` 子节点），可绕过类型白名单检查直接创建表。应增加 `tree.find(exp.Into)` 检查。 |
| **A5** | **P1** | AST 校验未递归检查 CTE 子句体                    | validator.py | `WITH cte AS (<body>) SELECT ...` 的顶层是 `exp.Select`，会通过类型检查，但 CTE body 理论上可以是 DML（某些方言支持 `WITH ... AS (DELETE ... RETURNING *)` ）。应对 `tree.find_all(exp.With)` 中的每个 CTE 表达式体做类型校验。 |
| **A6** | **P2** | DuckDB 连接无生命周期管理                        | sandbox.py   | `duckdb_dry_run` 接受外部传入的 `conn`，但 Agent 节点中没有任何创建/销毁/池化逻辑。高并发场景下每个请求如果各自 `duckdb.connect(":memory:")`，会产生大量独立连接和内存占用。建议引入连接池或单例 + `EXPLAIN` 级别锁。 |

---

## 二、状态管理与并发安全 (State & Concurrency)

### 2.1 节点返回 partial dict 一致性

| 节点                 | 返回字段                                           | 合规 | 备注             |
| -------------------- | -------------------------------------------------- | ---- | ---------------- |
| `parse_intent_node`  | `{"intent": ...}`                                  | ✅    |                  |
| `search_schema_node` | `{"candidate_tables": ..., "schema_context": ...}` | ✅    |                  |
| `generate_sql_node`  | `{"generated_sql": ...}`                           | ✅    |                  |
| `validate_sql_node`  | `{"validation_errors": ...}`                       | ✅    | 每次覆盖而非累加 |
| `fix_sql_node`       | `{"retry_count": ...}`                             | ✅    |                  |
| `transpile_sql_node` | `{"transpiled_sql": ..., "validation_errors": []}` | ✅    | 主动清空错误     |
| `respond_node`       | `{"status": ..., "error_message": ...}`            | ✅    |                  |

### 2.2 发现的问题

| #      | 等级   | 问题                                                       | 文件                  | 详情                                                         |
| ------ | ------ | ---------------------------------------------------------- | --------------------- | ------------------------------------------------------------ |
| **S1** | **P1** | 纠错循环中 `schema_context` 和 `candidate_tables` 可能过期 | nodes.py              | 重试时 `generate_sql_node` 复用 `state.schema_context`（第一次 RAG 的结果），不会重新检索。如果第一次 Schema 检索结果不佳导致生成失败，后续重试依然使用同一批 Schema，LLM 无从修正"缺表"类错误。建议在 `retry_count > 1` 时允许重新触发 `search_schema`。 |
| **S2** | **P1** | `validation_errors` 在 `generate_sql_node` 中未被清空      | nodes.py              | `generate_sql_node` 返回 `{"generated_sql": result.sql}`，没有同时返回 `"validation_errors": []`。这意味着在进入 `validate_sql_node` 之前，State 中仍残留上一轮的错误列表。虽然 `validate_sql_node` 会整体覆盖，但如果后续有其他节点在此期间读取 `validation_errors`（如日志记录、观测性节点），会拿到脏数据。 |
| **S3** | **P1** | 全局可变单例非线程安全                                     | nodes.py, embedder.py | `_qdrant_client`、`_embedder`、`_model` 三个全局变量使用无锁懒初始化。在 Uvicorn 多线程（或 `workers>1` 多进程）模式下不安全。多进程各自独立无问题，但单进程 + `asyncio.to_thread` 场景存在竞态。建议使用 `functools.lru_cache` 或 FastAPI `Depends` 生命周期注入。 |
| **S4** | **P2** | `respond_node` 条件判断有逻辑罅隙                          | nodes.py              | `if state.validation_errors or state.retry_count >= state.max_retries` — 当 `retry_count == max_retries` 但 `validation_errors == []`（理论上不可能但属于防御编程范畴），会误判为失败。建议优先判断 `validation_errors` 是否为空，再决定状态。 |

---

## 三、代码规范与异味 (Code Smells)

### 3.1 Pydantic v2 合规性 — 全面合规 ✅

所有模型均使用 `BaseModel`（pydantic v2）、`BaseSettings`（pydantic-settings v2）、`model_config` dict 语法，类型注解使用 `list[str]`、`str | None` 等 Python 3.10+ 语法。无 v1 遗留写法。

### 3.2 发现的问题

| #      | 等级   | 问题                                      | 文件                             | 详情                                                         |
| ------ | ------ | ----------------------------------------- | -------------------------------- | ------------------------------------------------------------ |
| **C1** | **P1** | 节点函数无异常处理                        | nodes.py                         | AGENTS.md 明确要求"在 `agent/nodes.py` 节点函数中捕获异常并写入 `AgentState.validation_errors`，不要在内部模块 silent pass"。但实际所有 6 个节点函数**均无 try-except**。如果 Qdrant 不可达、LLM API 超时、sqlglot 转译失败，异常会直接穿透到 LangGraph 运行时导致未处理的 crash。尤其 `transpile_sql_node` 调用的 `transpile_sql()` 会抛 `ValueError`。 |
| **C2** | **P1** | DuckDB 错误消息直接暴露给 LLM             | sandbox.py                       | `f"DuckDB dry-run 失败: {e}"` 包含 DuckDB 的完整内部错误堆栈和路径信息。当这些信息通过 `validation_errors` 喂回 LLM 的 FIX prompt 时，会浪费大量 Token 且可能误导 LLM（DuckDB 方言特有的错误信息 vs 目标方言）。应提取关键错误信息并截断。 |
| **C3** | **P1** | TECH_DESIGN 定义的文件缺失                | TECH_DESIGN.md §2                | `agent/tools.py`（Agent 工具函数）、`sql/generator.py`（SQL 生成独立模块）在 TECH_DESIGN 中列出但未创建。虽然 MVP 将生成逻辑放在 nodes.py 中是合理简化，但 nodes.py 中的 `generate_sql_node` 承担了 LLM 调用 + prompt 拼装的职责，违反了"节点只做编排调度，具体实现委托给子模块"的原则。 |
| **C4** | **P2** | indexer.py 使用 MD5 生成 Qdrant 点 ID     | indexer.py                       | `hashlib.md5(table.full_name.encode()).hexdigest()` 生成 32 字符的十六进制字符串。Qdrant `PointStruct.id` 接受 `str | int`，此处 string 格式可以工作，但如果后续 Qdrant 版本收紧为仅 UUID 格式，会出错。且 MD5 存在碰撞风险（虽然对表名量级极低）。建议使用 `uuid5(NAMESPACE_DNS, full_name)` 生成确定性 UUID。 |
| **C5** | **P2** | 测试中 mock side_effect 大量重复          | conftest.py, test_agent_graph.py | conftest.py 中的 `_create_response` 和 test_agent_graph.py 中的 `side_effect` 分别实现了同一套 `response_model` 分发逻辑，可抽为共享 fixture helper。 |
| **C6** | **P2** | `to_schema_text()` 中分区键信息可能不一致 | schema.py                        | `partition_keys` 默认为 `[]` 但 `to_schema_text` 直接 join，当为空时输出 `[分区键: ]`，可读性差，喂给 LLM 时可能产生误解（是分区表还是非分区表？）。建议空列表时输出 `[无分区键]`。 |

---

## 四、M3 接口演进就绪度 (API Readiness)

| #      | 等级   | 问题                                  | 影响                                                         | 改进思路                                                     |
| ------ | ------ | ------------------------------------- | ------------------------------------------------------------ | ------------------------------------------------------------ |
| **M1** | **P0** | 全同步链路阻塞事件循环                | nodes.py 中所有节点均为 `def`（同步），内含 `OpenAI().chat.completions.create()`、`QdrantClient.query_points()`、`SentenceTransformer.encode()` 三类阻塞 I/O 调用。若直接在 FastAPI `async def` 路由中 `await graph.ainvoke()`，同步调用会阻塞整个 uvicorn 事件循环。 | **方案 A**（推荐）：将 `OpenAI` 换为 `AsyncOpenAI`，`QdrantClient` 换为 `AsyncQdrantClient`，节点改为 `async def`，`SentenceTransformer.encode()` 用 `asyncio.to_thread()` 包裹。<br/>**方案 B**（过渡）：在 FastAPI 路由中用 `asyncio.to_thread(graph.invoke, state)` 将整图推入线程池。 |
| **M2** | **P1** | `graph` 模块级编译无法支持请求级配置  | graph.py `graph = build_graph().compile()` 在 import 时触发。所有请求共享同一 compiled graph，无法注入 per-request 的 DuckDB 连接、checkpointer 等。 | 改为 `build_graph()` + 延迟 `compile()`，或在 FastAPI 的 `Depends` 中提供 graph 实例工厂。 |
| **M3** | **P1** | 缺少 DuckDB 连接的 DI 机制            | DuckDB 连接未出现在 Agent 管道中（参见 A1），M3 接入时需要一套完整的连接生命周期管理（创建→虚拟表同步→dry-run→关闭）。目前没有 FastAPI `Depends` 可供注入。 | 建议在 `sql/sandbox.py` 中封装 `SandboxManager` context manager，提供 `create_sandbox(tables) -> conn`，内置安全初始化 + 自动关闭。在 agent 节点中通过 state 或 DI 获取。 |
| **M4** | **P2** | `QueryResponse` 缺少 `reasoning` 字段 | query.py                                                     | `GeneratedSQL.reasoning` 包含 CoT 推理过程，但 `QueryResponse` 没有此字段，前端无法展示 SQL 生成的推理链路（这在数据分析场景中对用户建立信任很重要）。 |

---

## 五、总结与优先级路线图

### 统计

| 等级            | 数量  | 说明                                   |
| --------------- | ----- | -------------------------------------- |
| **P0 致命隐患** | **4** | A1, A2, A3, M1                         |
| **P1 代码异味** | **8** | A4, A5, S1, S2, S3, C1, C2, C3, M2, M3 |
| **P2 优化建议** | **5** | A6, S4, C4, C5, C6, M4                 |

### 建议修复路线（进入 M3 前须完成 P0）

```
┌─── Sprint 0（M3 前置 Hotfix）──────────────────────────────────┐
│ A2. sandbox.py 添加 enable_external_access = false             │
│ A3. sync_virtual_tables 使用 sqlglot 标识符转义               │
│ A1. validate_sql_node 集成 duckdb_dry_run                     │
│ A1. 补充 DuckDB 连接创建 + SandboxManager 封装                │
│ M1. 节点改 async def + AsyncOpenAI + AsyncQdrantClient         │
│ C1. 所有节点函数添加 try-except → validation_errors / status   │
└────────────────────────────────────────────────────────────────┘
         ↓
┌─── M3 开发同步修复 ───────────────────────────────────────────┐
│ M2. graph compile 延迟化 + FastAPI DI                          │
│ M3. SandboxManager 注入到 agent 节点                          │
│ S1. 重试 > 1 时可选重跑 search_schema                         │
│ S3. 全局单例改 lru_cache 或 Depends                           │
│ A4. validate_sql 增加 SELECT INTO 检查                         │
│ A5. validate_sql 递归检查 CTE 子体                             │
│ C2. DuckDB 错误消息截断处理                                    │
└────────────────────────────────────────────────────────────────┘
```

以上即为本轮全局审计的全部发现。4 个 P0 问题中，**A1（DuckDB 沙盒断连管道）** 和 **A2（沙盒缺少安全开关）** 最为紧迫——前者意味着整个 Dry-run 校验层形同虚设，后者在接入真实流量后是直接的安全漏洞。建议在启动 M3 API 开发前作为阻塞项完成修复。