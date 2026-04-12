# LakeQuery 开发规范

## 项目概述

NL2SQL Agent 中间件，面向湖仓一体架构。技术详情见 [PRD.md](PRD.md) 和 [TECH_DESIGN.md](TECH_DESIGN.md)。

## 代码风格

- Python 3.11+，全面使用类型注解（`list[str]` 而非 `List[str]`，`str | None` 而非 `Optional[str]`）
- 数据模型统一用 Pydantic v2 BaseModel，禁止使用 dataclass 或 TypedDict
- 异步优先：FastAPI 路由和 LLM 调用使用 `async def`；纯计算函数（sqlglot 解析、DuckDB 校验）用同步 `def`
- 导入顺序：stdlib → 第三方 → 本项目，各组之间空一行
- 字符串统一用双引号 `"`
- 文件顶部不写模块级 docstring，函数/类只在逻辑不明显时写简短 docstring

## 架构约束

### 目录结构（必须遵守）

```
lakequery/
├── main.py          # FastAPI 入口，只做 app 初始化和路由挂载
├── config.py        # Pydantic Settings，所有配置集中在此
├── models/          # 纯数据模型，无业务逻辑
├── agent/           # LangGraph 状态机 + 节点实现
│   ├── graph.py     # 只定义图结构和边，不写业务逻辑
│   ├── nodes.py     # 每个节点是一个函数，输入输出都是 AgentState
│   ├── prompts.py   # MVP 阶段 Prompt 以常量形式集中管理
│   └── tools.py     # Agent 工具函数
├── catalog/         # 元数据适配器（HMS / Iceberg REST）
├── rag/             # 向量检索（Qdrant）
├── sql/             # SQL 处理（生成/校验/沙盒/转译）
├── api/             # FastAPI 路由
├── ui/              # Gradio 前端
└── tests/           # 测试
```

### 层级依赖规则

```
ui / api → agent → rag, sql, catalog → models, config
```

- **禁止反向依赖**：`models/` 和 `config.py` 不能 import 任何其他业务模块
- **禁止跨层调用**：`api/` 不能直接调用 `sql/` 或 `catalog/`，必须经过 `agent/`
- `agent/nodes.py` 中的每个节点函数只做编排调度，具体实现委托给 `rag/`、`sql/`、`catalog/` 中的函数

## TDD 开发流程

**所有核心函数必须先写测试再写实现**，这是质量底线。

### 开发一个功能的标准步骤

1. 在 `tests/unit/` 或 `tests/integration/` 中编写测试用例（至少覆盖 happy path + 一个异常 case）
2. 运行测试，确认测试失败（红）
3. 编写最小实现代码，使测试通过（绿）
4. 如有必要再重构

### 测试约定

- 单元测试放 `tests/unit/`，集成测试放 `tests/integration/`
- 测试数据放 `tests/fixtures/`（JSON 格式）
- 测试函数命名：`test_<功能>_<场景>` （如 `test_validate_sql_rejects_insert`）
- LLM 调用必须 mock，单元测试**绝不消耗** API Token
- DuckDB 测试用 `:memory:` 连接
- 运行测试命令：`pytest tests/ -v`
- 运行单个模块测试：`pytest tests/unit/test_validator.py -v`

## 编码规则

### 必须遵守

- 新文件必须在对应 `__init__.py` 中导出公共接口
- 所有配置通过 `config.py` 的 `Settings` 类读取，禁止硬编码配置值
- LLM 调用统一用 Instructor 包装，返回 Pydantic 模型，禁止手动解析 LLM 文本输出
- SQL 安全：sqlglot 解析后只允许 `SELECT` 语句，遇到 `INSERT/UPDATE/DELETE/DROP/CREATE/ALTER` 立即拒绝
- DuckDB 沙盒初始化时必须执行 `SET enable_external_access = false`
- 错误处理：在 `agent/nodes.py` 节点函数中捕获异常并写入 `AgentState.validation_errors`，**不要**在内部模块抛出后 silent pass

### 禁止事项

- 禁止使用 `print()` 调试，用 `logging` 模块
- 禁止 `from xxx import *`
- 禁止在函数中修改全局状态
- 禁止写直接操作文件系统的代码（除了 config 中指定的路径）
- MVP 阶段禁止引入 PRD/TECH_DESIGN 中未列出的第三方依赖（需要先讨论）
- 禁止在 `models/` 目录的文件中写业务逻辑（只放数据结构定义和序列化方法）

## LangGraph 状态机规范

- 全局状态类型为 `AgentState`（定义在 `models/state.py`）
- 每个节点函数签名：`def node_name(state: AgentState) -> AgentState`
- 节点函数只修改自己负责的 state 字段（见 TECH_DESIGN.md §4.2 节点职责表）
- 条件路由函数放在 `agent/graph.py` 中，命名为 `route_after_<node_name>`
- 纠错循环最多重试 `state.max_retries` 次（默认 3 次），超限后设置 `status = "failed"` 并终止

## Prompt 管理

- MVP 阶段所有 Prompt 以 Python 字符串常量形式放在 `agent/prompts.py`
- 常量命名：`SYSTEM_<功能>` / `USER_<功能>`（如 `SYSTEM_GENERATE_SQL`、`USER_FIX_SQL`）
- Prompt 中需要动态填充的部分用 `{variable_name}` 占位，通过 `.format()` 注入
- 修改 Prompt 时必须同步更新对应的测试用例

## Git 规范

- 分支命名：`feat/<功能>`、`fix/<问题>`、`test/<测试>`
- Commit message 格式：`<type>: <简要描述>`
  - type: `feat` | `fix` | `test` | `refactor` | `docs` | `chore`
  - 示例：`feat: 实现 sqlglot AST 校验节点`
- 每个 commit 应该能独立通过 `pytest tests/`

## 构建与运行

```bash
# 安装依赖
pip install -r requirements.txt

# 运行测试
pytest tests/ -v

# 启动后端
uvicorn lakequery.main:app --reload --port 8000

# 启动前端（另一个终端）
python -m lakequery.ui.app
```
