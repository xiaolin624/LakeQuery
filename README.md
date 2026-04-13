<p align="center">
  <h1 align="center">🏔️ LakeQuery</h1>
  <p align="center">
    <strong>面向湖仓一体架构的 NL2SQL 智能体中间件</strong><br/>
    基于 LangGraph 状态机 + AST 级安全校验 + DuckDB 沙盒隔离，<br/>
    让业务分析师用自然语言安全查询 PB 级 Hive/Iceberg 数据湖。
  </p>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.11+-blue?logo=python&logoColor=white" alt="Python"/>
  <img src="https://img.shields.io/badge/Next.js-16-black?logo=next.js" alt="Next.js"/>
  <img src="https://img.shields.io/badge/FastAPI-0.135-009688?logo=fastapi" alt="FastAPI"/>
  <img src="https://img.shields.io/badge/LangGraph-1.1-orange" alt="LangGraph"/>
  <img src="https://img.shields.io/badge/tests-85%20passed-brightgreen" alt="Tests"/>
  <img src="https://img.shields.io/badge/license-MIT-green" alt="License"/>
</p>

---

## 📖 项目简介

**LakeQuery** 是一款开源的 NL2SQL（自然语言转 SQL）智能体中间件，专为湖仓一体架构设计。它解决了企业数据团队面临的核心痛点：**业务分析师不会写 SQL，数据工程师 80% 的时间在处理临时取数需求**。

与 Vanna、SQLChat 等现有方案不同，LakeQuery 不是一个简单的 Prompt → SQL 转换器。它是一个**具备完整防护体系的 Agent 系统**——通过 sqlglot AST 语法树校验拦截非法操作（DDL/DML），通过 DuckDB 沙盒 Dry-run 在本地验证语法正确性，通过分区键裁剪校验防止全表扫描雪崩，全链路保障生成的 SQL 安全可靠。

---

## ✨ 核心特性

| 特性 | 描述 |
|------|------|
| 🧠 **LangGraph 状态机编排** | 8 节点有向图（意图解析 → Schema 检索 → SQL 生成 → 校验 → 纠错循环 → 转译 → 响应），支持最多 3 次自动纠错重试 |
| 🛡️ **AST 级安全校验** | sqlglot 解析 SQL 抽象语法树，白名单仅放行 `SELECT`/`UNION`/`INTERSECT`/`EXCEPT`，拦截一切 DDL/DML 写操作 |
| 🏖️ **DuckDB 沙盒隔离** | 在内存中构建虚拟 Schema 镜像，`enable_external_access=false` 完全隔离，Dry-run 验证语法与类型 |
| 🔀 **多方言转译** | 基于 sqlglot 支持 Hive / Spark / Trino / Presto / DuckDB 方言自动转译 |
| 📊 **Schema RAG 检索** | 元数据向量化存储至 Qdrant，基于 BGE-large-zh-v1.5 中文语义检索 Top-K 相关表 |
| 🏗️ **真实湖仓对接** | 已验证连接 Hive Metastore（Thrift 协议），支持 Iceberg REST Catalog |
| 🎯 **黄金查询记忆库** | 已验证的 SQL 存入向量库，相似问题直接复用，阈值 0.95 高精度匹配 |
| 📱 **现代 B2B 控制台** | Next.js 16 + React 19 + shadcn/ui + Tailwind CSS 4，极简专业的数据工程师控制台 |
| 🔍 **元数据智能问答** | 自动识别元数据查询（表数量/结构/字段），直接从 Catalog 索引回答，无需生成 SQL |
| 🐳 **一键部署** | Docker Compose 编排 Qdrant + FastAPI 后端，零配置本地启动 |

---

## 🏗️ 技术栈全景图

<img width="1024" height="559" alt="image" src="https://github.com/user-attachments/assets/c4cf22e8-a466-4983-a06f-f3d0c85eeec3" />


---

## 🔄 架构数据流

从用户输入自然语言到获得经过校验的 SQL，完整链路如下：

```
用户: "查一下2026年3月各省份的DAU日均值，按降序排列"
  │
  ▼ ① 意图解析 (parse_intent)
  │  Instructor + LLM → ParsedIntent{time="2026-03", dims=["省份"], metrics=["DAU"]}
  │  检测到 is_metadata_query? → 走元数据快速通道
  │
  ▼ ② 黄金查询匹配 (check_golden)
  │  Qdrant 相似度 ≥ 0.95 → 直接复用历史验证 SQL
  │
  ▼ ③ Schema RAG 检索 (search_schema)
  │  BGE-large-zh 编码 → Qdrant 向量搜索 Top-10 → 按 database 过滤
  │  输出: candidate_tables + schema_context 文本
  │
  ▼ ④ SQL 生成 (generate_sql)
  │  Instructor + LLM → GeneratedSQL{sql, reasoning, tables_used}
  │  强制返回 Pydantic 模型，拒绝手动解析
  │
  ▼ ⑤ 双重校验 (validate_sql)
  │  [a] sqlglot AST：白名单 SELECT-only + 表名/列名交叉验证 + 分区键裁剪检查
  │  [b] DuckDB Dry-run：沙盒内 EXPLAIN 验证语法/类型
  │  校验失败 → fix_sql → 重新生成（最多 3 次）
  │
  ▼ ⑥ 方言转译 (transpile_sql)
  │  sqlglot.transpile(sql, read="duckdb", write=target_dialect)
  │
  ▼ ⑦ 响应 (respond)
     返回 {sql, dialect, tables_used, validation_passed, answer}
```

---

## 📁 项目结构

```
LakeQuery/
├── lakequery/                   # Python 后端核心
│   ├── main.py                 # FastAPI 入口 + Qdrant 集合初始化
│   ├── config.py               # Pydantic Settings 集中配置
│   ├── agent/                  # LangGraph 状态机
│   │   ├── graph.py            # 图结构定义 + 条件路由
│   │   ├── nodes.py            # 8 个节点函数实现
│   │   └── prompts.py          # Prompt 常量管理
│   ├── models/                 # Pydantic 数据模型
│   │   ├── state.py            # AgentState 全局状态
│   │   ├── query.py            # 请求/响应/意图/SQL 模型
│   │   └── schema.py           # TableMeta/ColumnMeta 元数据
│   ├── catalog/                # 元数据适配器
│   │   ├── hms.py              # Hive Metastore (Thrift)
│   │   ├── iceberg_rest.py     # Iceberg REST Catalog
│   │   └── local.py            # 本地 JSON 兜底
│   ├── rag/                    # 向量检索
│   │   ├── embedder.py         # BGE-large-zh 编码器
│   │   ├── indexer.py          # 元数据向量化入库
│   │   └── retriever.py        # Schema/Golden Query 检索
│   ├── sql/                    # SQL 安全处理
│   │   ├── validator.py        # AST 白名单校验 + 分区检查
│   │   ├── sandbox.py          # DuckDB 沙盒 Dry-run
│   │   └── transpiler.py       # 多方言转译
│   └── api/
│       └── routes.py           # REST 接口 (/query, /catalog/sync, /health)
│
├── lakequery-web/               # Next.js 16 现代前端
│   ├── app/                    # App Router 页面
│   │   ├── page.tsx            # 主查询页 (NL → SQL)
│   │   ├── catalog/page.tsx    # Catalog 管理 (HMS 连接/同步)
│   │   └── settings/page.tsx   # LLM & 系统配置
│   ├── components/ui/          # shadcn/ui 组件库
│   ├── lib/store.ts            # Zustand 全局状态 (持久化)
│   └── types/schema.ts         # TypeScript 类型定义
│
├── tests/                       # 测试套件 (85 tests)
│   ├── unit/                   # 63 单元测试
│   └── integration/            # 22 集成测试
│
├── docker-compose.yml           # Qdrant + FastAPI 编排
├── Dockerfile                   # Python 3.11-slim 多层构建
├── requirements.txt             # 24 依赖声明
└── .env.example                 # 环境变量模板
```

---

## 🚀 快速开始

### 方式一：Docker Compose 一键启动

```bash
# 1. 克隆仓库
git clone https://github.com/<your-username>/LakeQuery.git
cd LakeQuery

# 2. 配置环境变量
cp .env.example .env
# 编辑 .env，填入 LLM API Key：
#   LQ_LLM_API_KEY=your-api-key
#   LQ_LLM_BASE_URL=https://ark.cn-beijing.volces.com/api/v3
#   LQ_LLM_MODEL=your-model-endpoint

# 3. 启动（Qdrant + FastAPI 后端）
docker-compose up -d

# 4. 验证
curl http://localhost:8000/api/v1/health
```

### 方式二：本地开发环境

```bash
# 后端
cd LakeQuery
python -m venv .venv && .venv\Scripts\activate  # Windows
pip install -r requirements.txt
uvicorn lakequery.main:app --reload --port 8000

# 前端（另一个终端）
cd lakequery-web
npm install
npm run dev
# 访问 http://localhost:3000
```

### 前端环境变量

在 `lakequery-web/` 下创建或编辑 `next.config.ts`，配置 API 代理：

```typescript
// next.config.ts 已预配置 rewrites → http://localhost:8000
```

### 连接真实 Hive 环境

1. 进入前端 **Catalog** 页面
2. 填写 HMS 地址（如 `192.168.10.102:10000`）
3. 设置用户名（需有 HDFS 读权限的用户）
4. 点击 **Sync** 同步元数据到 Qdrant
5. 回到主查询页，用自然语言提问即可

---

## 🧪 测试

```bash
# 运行全部 85 个测试
pytest tests/ -v

# 仅运行单元测试
pytest tests/unit/ -v

# 运行特定模块
pytest tests/unit/test_validator.py -v
```

测试覆盖：
- **SQL 校验**：DDL/DML 拦截、表名列名验证、分区键裁剪、CTE 嵌套 DML 拦截（25 tests）
- **DuckDB 沙盒**：虚拟表同步、Dry-run 成功/失败、SQL 注入防护（8 tests）
- **方言转译**：Hive/Spark/Trino 转译正确性（4 tests）
- **Agent 节点**：意图解析、SQL 生成、Schema 检索 mock 测试（11 tests）
- **集成测试**：完整 Agent Graph 端到端 + FastAPI 接口测试（22 tests）

---

## 📐 设计决策

| 决策 | 选择 | 理由 |
|------|------|------|
| Agent 框架 | LangGraph > LangChain Agent | 状态机精确控制纠错循环流程，避免 ReAct 的不确定性 |
| SQL 校验 | sqlglot AST > 正则匹配 | AST 级精确识别语句类型，防御 CTE 嵌套 DML 等高级攻击 |
| 沙盒 | DuckDB > 正式引擎 EXPLAIN | 零部署、毫秒级、完全隔离，不消耗集群资源 |
| 结构化输出 | Instructor > 手动解析 | 强类型校验 LLM 输出，自动重试解析失败 |
| 前端 | Next.js 16 > Gradio | 企业级 B2B 控制台需要自定义 UI、状态持久化、多页面路由 |
| 状态管理 | Zustand + persist > Redux | 轻量、SSR 兼容、内置持久化中间件 |
| 向量库 | Qdrant > ChromaDB | 生产级性能、payload filter 支持、本地/云端无缝切换 |

---

## 📄 License

MIT

---

<p align="center">
  <sub>Built with ❤️ for the lakehouse community</sub>
</p>
