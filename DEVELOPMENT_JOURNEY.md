# LakeQuery 开发纪实：从零到全栈 NL2SQL 智能体

> 本文档以里程碑时间线的方式，完整记录了 LakeQuery 项目从架构设计到真实湖仓对接的全过程，重点复盘关键技术挑战及解决方案。

---

## 🗺️ 里程碑全景

```
M1 骨架搭建 → M2 核心链路 → M3 前端集成 → M4 安全加固 → M5 多引擎扩展
     │              │             │              │              │
     ▼              ▼             ▼              ▼              ▼
  FastAPI       LLM+校验      Gradio UI      黄金查询      Iceberg+转译
  +LangGraph    +DuckDB沙盒   → Next.js重构   +分区裁剪     +HMS真实对接
  +Qdrant RAG   +纠错循环     +shadcn/ui     +CTE拦截      +元数据问答
```

---

## M1：骨架搭建 — "先有骨架，再长肉"

### 目标
搭建项目基本骨架：FastAPI 后端 + LangGraph Agent 状态机 + HMS 元数据拉取 + Qdrant 向量化。

### 关键决策

**为什么选择 LangGraph 而非 LangChain ReAct Agent？**

这是项目最重要的架构决策之一。NL2SQL 的核心难点不是"生成"——任何 LLM 都能生成 SQL——而是**生成后的校验-纠错循环**。我们需要：

1. 精确控制流程：校验失败 → 注入错误信息 → 重新生成 → 再校验，最多 3 次
2. 每个节点职责单一：意图解析、Schema 检索、SQL 生成、校验、转译各自独立
3. 条件路由可预测：不依赖 LLM 自行决定"下一步做什么"

LangGraph 的 `StateGraph` + `add_conditional_edges` 完美满足这些需求。相比 ReAct，它的行为是**确定性的**——同样的输入永远走同样的路径，这对生产环境至关重要。

**为什么用 Instructor 而不是手动解析 LLM 输出？**

早期实验中，直接让 LLM 返回 SQL 文本，经常出现：
- 返回的 SQL 被 Markdown 代码块包裹（```sql ... ```）
- 夹杂解释性文字
- JSON 格式不严格

引入 Instructor 后，LLM 的输出**被强制映射到 Pydantic 模型**（`ParsedIntent`、`GeneratedSQL`），完全消除了手动解析的脆弱性。

### 技术实现

```python
# AgentState —— 全局状态在节点间流转
class AgentState(BaseModel):
    user_query: str
    target_dialect: str = "hive"
    intent: dict | None = None
    candidate_tables: list = []
    schema_context: str = ""
    generated_sql: str = ""
    validation_errors: list[str] = []
    retry_count: int = 0
    max_retries: int = 3
    status: Literal["pending", "success", "failed"] = "pending"
```

### TDD 先行

项目从第一天起严格执行 TDD（测试驱动开发）。每个模块的开发流程：

1. 在 `tests/unit/` 编写测试用例（至少 happy path + 异常 case）
2. 确认测试红灯
3. 编写最小实现
4. 绿灯 → 重构

最终积累了 **85 个测试用例**（63 单元 + 22 集成），覆盖 SQL 校验、沙盒、转译、节点、API 全链路。

---

## M2：核心链路 — "能生成 SQL 了，但不敢直接用"

### 目标
打通 LLM 生成 SQL + sqlglot 校验 + DuckDB Dry-run + 自动纠错循环。

### 关键挑战：DuckDB 沙盒的虚拟表同步

**问题**：DuckDB Dry-run 需要知道远端 Hive 表的 Schema 才能验证 SQL 语法。但 DuckDB 是纯内存数据库，完全没有远端表信息。

**解决方案**：在 `/catalog/sync` 时，同步在 DuckDB 中创建**同构空表**：

```python
# sandbox.py - 核心思路
def sync_virtual_tables(conn, tables: list[TableMeta]):
    for table in tables:
        conn.execute(f"CREATE SCHEMA IF NOT EXISTS {table.database}")
        col_defs = ", ".join(
            f"{c.name} {type_map.get(c.data_type.upper(), 'VARCHAR')}"
            for c in table.columns
        )
        conn.execute(f"CREATE OR REPLACE TABLE {table.full_name} ({col_defs})")
```

关键设计：
- 虚拟表**只有结构没有数据**，`EXPLAIN` 只做语法/类型检查
- Hive 类型 → DuckDB 类型映射（`STRING→VARCHAR`, `BIGINT→BIGINT` 等），未知类型退化为 `VARCHAR`
- 安全隔离：启动时 `SET enable_external_access = false`，彻底阻断文件系统/网络访问

### AST 校验的深度防御

简单的正则匹配（如 `sql.strip().upper().startswith("SELECT")`）远远不够。攻击者可以用 CTE 嵌套绕过：

```sql
-- 正则误判为 SELECT，实际包含 DELETE
WITH tmp AS (SELECT 1)
DELETE FROM users WHERE id IN (SELECT * FROM tmp)
```

我们的 `validator.py` 使用 sqlglot 解析 AST 后，递归检查所有节点类型：

```python
_FORBIDDEN_TYPES = (
    exp.Insert, exp.Update, exp.Delete,
    exp.Drop, exp.Create, exp.AlterTable,
)

for statement in parsed:
    if isinstance(statement, _FORBIDDEN_TYPES):
        errors.append(f"禁止的语句类型: {type(statement).__name__}")
    # 递归检查 CTE 内部
    for node in statement.walk():
        if isinstance(node, _FORBIDDEN_TYPES):
            errors.append(...)
```

### 分区键裁剪校验

在 PB 级数据湖上，忘记加分区条件可能导致**全表扫描雪崩**。校验器自动检查：

```python
# 如果表有分区键（如 dt），SQL 的 WHERE 子句必须包含该分区键
# 缺失则返回警告而非阻断，让用户自行决定
```

---

## M3：前端集成 — "从 Gradio 到 Next.js 的涅槃重生"

### 为什么从 Gradio 迁移到 Next.js？

Gradio 在 MVP 阶段非常好用——零配置、自带 Chat UI、Python 生态无缝对接。但随着需求深入，它的局限暴露了：

| 痛点 | Gradio | Next.js |
|------|--------|---------|
| **多页面路由** | 不支持，单页面应用 | App Router 原生支持 |
| **自定义 UI** | 组件库有限，样式难调 | shadcn/ui + Tailwind 完全自由 |
| **状态持久化** | 刷新即丢失 | Zustand + localStorage persist |
| **企业级交互** | Chat 形式不适合 B2B 场景 | 表单 + 配置面板 + 结果可视化 |
| **前后端分离** | Python 耦合 | 独立部署、独立迭代 |

最终选型：**Next.js 16 + React 19 + shadcn/ui + Tailwind CSS 4 + Zustand 5**。

### 前端架构

```
lakequery-web/
├── app/
│   ├── page.tsx          # 主查询页：输入 → SQL 展示 → 结果表格
│   ├── catalog/page.tsx  # Catalog 管理：HMS 连接配置 + 表同步
│   ├── settings/page.tsx # 系统设置：LLM 配置
│   └── layout.tsx        # 全局布局 + 侧边导航
├── lib/store.ts          # Zustand 全局状态（LLM/Catalog/Query 三大模块）
└── types/schema.ts       # TypeScript 类型定义
```

### Hydration Mismatch：SSR 与客户端状态的经典冲突

**问题现象**：页面加载时 React 报 `Hydration failed because the initial UI does not match what was rendered on the server`。

**根因分析**：
- Zustand 的 `persist` 中间件从 `localStorage` 恢复状态
- 服务端渲染时 `localStorage` 不存在，状态为默认值
- 客户端 hydration 时状态为恢复后的值
- 两者不匹配 → React 报错

**解决方案**：自定义 `useHydrated()` Hook + `onRehydrateStorage` 回调：

```typescript
// 1. 在 Zustand store 中标记 hydration 完成
persist({...}, {
  onRehydrateStorage: () => (state) => {
    state?.setHasHydrated(true);
  },
})

// 2. 自定义 Hook 等待 hydration
function useHydrated() {
  const hasHydrated = useAppStore((s) => s._hasHydrated);
  return hasHydrated;
}

// 3. 组件中：hydration 未完成时返回骨架屏
if (!hydrated) return <Skeleton />;
```

这个方案确保了 SSR 渲染的 HTML 与客户端首次渲染完全一致，消除了 Hydration 报错。

---

## M4：安全加固 — "让每一条 SQL 都经得起质疑"

### 黄金查询记忆库

用户确认 SQL 正确后，将 `(自然语言, SQL)` 对向量化存入 Qdrant 的 `golden_queries` 集合。后续相似问题（余弦相似度 ≥ 0.95）直接复用，跳过 LLM 生成。

这不仅提升了效率，更建立了一个**持续进化的知识库**——使用越多，系统越准确。

### CTE 嵌套 DML 拦截

第 25 个测试用例发现了一个边缘 case：

```sql
WITH summary AS (SELECT department, COUNT(*) FROM emp GROUP BY department)
INSERT INTO report SELECT * FROM summary
```

sqlglot 解析后顶层节点是 `INSERT`，但如果只检查第一个 token 是 `WITH`，正则方案会误判为 SELECT。AST 校验自然免疫这类攻击。

---

## M5：多引擎与真实对接 — "从模拟到实战"

### 连接真实 Hive Metastore

这是项目从"demo"走向"可用"的关键一步。目标环境：
- Hadoop 集群：`192.168.10.102`
- HiveServer2 端口：`10000`
- 数据库：`gmall`（79 张表）

### 挑战一：PyHive 认证模式的迷宫

**症状**：`pyhive.connect()` 默认使用 `NOSASL` 认证，但集群配置为 `NONE`，导致 `TSocket read 0 bytes`。

**排查过程**：
1. 尝试 `auth='NOSASL'` → 连接建立但立即断开
2. 安装 `thrift-sasl` + `pure-sasl`，尝试 `auth='NONE'` → 连接成功！但查询失败
3. 发现 `username` 参数决定了 HDFS 操作的身份

**最终方案**：
```python
connection = hive.connect(
    host="192.168.10.102",
    port=10000,
    auth="NONE",
    username="atguigu",  # 必须是有 HDFS 权限的用户
    database=database,
)
```

### 挑战二：HDFS 权限拒绝（AccessControlException）

**症状**：PyHive 连接成功但执行 `SHOW TABLES` 时报错：

```
Permission denied: user=hive, access=EXECUTE,
inode="/tmp/hive": atguigu:supergroup:drwx------
```

**根因**：Hive 的 `/tmp/hive` 目录由 `atguigu` 用户创建，权限为 `700`。PyHive 默认以 `hive` 用户连接，没有执行权限。

**解决方案**：将 `username` 改为 `atguigu`（集群的实际管理员用户）。同时在前端 Catalog 页面新增用户名输入框，让运维人员自行配置。

### 挑战三：数据库上下文缺失

**症状**：同步了 `gmall` 数据库的 79 张表后，问"查看库里的所有表"，LLM 却生成了引用 `trade_dwd`（本地 demo 库）的 SQL。

**根因追溯**：

```
QueryRequest → AgentState → search_schema_node → Qdrant
     ↑                           ↑
  没有 database 字段       没有 database 过滤
```

整个查询链路**完全没有传递数据库上下文**。Qdrant 检索时返回的是相似度最高的表，恰好是本地兜底数据（`trade_dwd`）。

**修复**：在 `QueryRequest`、`AgentState`、`search_schema_node` 三层全面注入 `database` / `target_database` 字段，Qdrant 检索时使用 `FieldCondition` 过滤：

```python
if database_hint:
    query_filter = Filter(must=[
        FieldCondition(key="database", match=MatchValue(value=database_hint))
    ])
```

### 元数据查询：跳出 SQL 的思维定式

**症状**：用户问"查询数据湖里面的表的个数"，系统无法生成 SQL。

**根因**：这类问题不应该走 SQL 生成管线。`SHOW TABLES` 被校验器拒绝（非 SELECT），`information_schema.tables` 也不存在于 Qdrant 索引中。

**解决方案**：在意图解析阶段检测 `is_metadata_query`，路由到专用的 `metadata_node`，直接从 Qdrant 已同步的表索引中回答：

```
parse_intent → is_metadata_query=true → metadata_node → respond
                                        ↓
                                   Qdrant.query(limit=200)
                                        ↓
                                   "gmall 中共有 79 张表：..."
```

---

## 技术演进总结

### 从 Mock 到 Real 的四次飞跃

| 阶段 | Mock 层 | Real 层 | 关键突破 |
|------|---------|---------|----------|
| M1-M2 | 本地 JSON 表元数据 | sqlglot + DuckDB | AST 校验框架 |
| M3 | Gradio Chat UI | Next.js 16 控制台 | SSR Hydration 解决 |
| M4-M5 | 固定 demo 数据集 | HMS `192.168.10.102` | Thrift 认证 + HDFS 权限 |
| 元数据 | 无 | Qdrant 元数据快速通道 | 跳出 SQL-only 思维 |

### 架构不变量（从始至终坚守的原则）

1. **只读安全**：永远只允许 SELECT，零 DDL/DML 风险
2. **沙盒隔离**：DuckDB `enable_external_access=false`，不信任任何生成的 SQL
3. **层级依赖**：`api → agent → rag/sql/catalog → models/config`，禁止反向依赖
4. **TDD 底线**：每个功能先写测试、再写实现，85 个测试全绿才允许推进
5. **结构化输出**：所有 LLM 返回值都经 Instructor + Pydantic 强制校验

### 工程量统计

| 维度 | 数量 |
|------|------|
| Python 后端文件 | 23 个模块 |
| 前端 TypeScript 文件 | 10+ 组件/页面 |
| 测试用例 | 85 个（63 单元 + 22 集成） |
| Agent 节点 | 8 个（含 metadata） |
| 支持方言 | 5 种（Hive/Spark/Trino/Presto/DuckDB） |
| 生产依赖 | 22 个 Python + 15 个 Node.js |

---

## 如果重新来过，我会做什么不同？

1. **更早引入 Next.js**：Gradio 在 M3 才暴露局限性，如果一开始就用 Next.js，可以省去迁移成本
2. **集成测试自动化**：HMS 的集成测试目前需要真实 Hadoop 集群，应该引入 Testcontainers 做容器化测试
3. **Prompt 版本管理**：MVP 阶段 Prompt 以 Python 常量管理够用，但随着迭代应尽早迁移到 YAML + 版本追踪
4. **前端 E2E 测试**：目前前端没有自动化测试，应该引入 Playwright 覆盖关键路径

---

> *"最好的架构不是一步到位设计出来的，而是在解决一个又一个真实问题中逐渐演化而来的。"*
