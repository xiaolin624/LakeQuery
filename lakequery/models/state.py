from typing import Literal

from pydantic import BaseModel

from lakequery.models.schema import TableMeta


class AgentState(BaseModel):
    # 输入
    user_query: str = ""
    target_dialect: str = "hive"
    target_database: str = ""
    conversation_id: str = ""

    # 意图解析结果
    intent: dict | None = None

    # Schema 检索结果
    candidate_tables: list[TableMeta] = []
    schema_context: str = ""

    # 黄金查询命中
    is_golden_hit: bool = False
    golden_sql_hint: str = ""

    # SQL 生成
    generated_sql: str = ""
    transpiled_sql: str = ""

    # 校验
    validation_errors: list[str] = []
    retry_count: int = 0
    max_retries: int = 3

    # 结果
    status: Literal["pending", "success", "failed"] = "pending"
    execution_result: list[dict] | None = None
    error_message: str = ""
    answer: str = ""
