import functools
import logging

import instructor
from openai import AsyncOpenAI
from qdrant_client import AsyncQdrantClient

from lakequery.agent.prompts import (
    SYSTEM_GENERATE_SQL,
    SYSTEM_PARSE_INTENT,
    USER_FIX_SQL,
    USER_GENERATE_SQL,
    USER_GENERATE_SQL_WITH_HINT,
)
from lakequery.config import settings
from lakequery.models.query import GeneratedSQL, ParsedIntent
from lakequery.models.state import AgentState
from lakequery.rag.retriever import search_golden_query, search_tables
from lakequery.sql.sandbox import SandboxManager, duckdb_dry_run
from lakequery.sql.transpiler import transpile_sql
from lakequery.sql.validator import validate_sql

logger = logging.getLogger(__name__)


@functools.lru_cache(maxsize=1)
def get_llm_client():
    return instructor.from_openai(
        AsyncOpenAI(
            base_url=settings.llm_base_url,
            api_key=settings.llm_api_key,
        )
    )


@functools.lru_cache(maxsize=1)
def get_qdrant_client() -> AsyncQdrantClient:
    return AsyncQdrantClient(
        url=settings.qdrant_url,
        api_key=settings.qdrant_api_key or None,
        check_compatibility=False,
    )


@functools.lru_cache(maxsize=1)
def get_embedder():
    from lakequery.rag.embedder import get_embedder as _load_embedder
    return _load_embedder()


async def parse_intent_node(state: AgentState) -> dict:
    try:
        client = get_llm_client()
        parsed: ParsedIntent = await client.chat.completions.create(
            model=settings.llm_model,
            response_model=ParsedIntent,
            messages=[
                {"role": "system", "content": SYSTEM_PARSE_INTENT},
                {"role": "user", "content": state.user_query},
            ],
            temperature=settings.llm_temperature,
        )
        return {"intent": parsed.model_dump()}
    except Exception as e:
        logger.error("parse_intent_node failed: %s", e)
        return {"status": "failed", "error_message": f"意图解析失败: {e}"}


async def check_golden_node(state: AgentState) -> dict:
    try:
        client = get_qdrant_client()
        embedder = get_embedder()
        sql = await search_golden_query(
            client, embedder, state.user_query,
            threshold=settings.golden_query_threshold,
        )
        if sql:
            return {"golden_sql_hint": sql, "is_golden_hit": True}
        return {}
    except Exception as e:
        logger.warning("黄金查询检索失败，继续正常流程: %s", e)
        return {"is_golden_hit": False}


async def generate_sql_node(state: AgentState) -> dict:
    try:
        client = get_llm_client()

        system_prompt = SYSTEM_GENERATE_SQL.format(
            schema_context=state.schema_context,
        )

        if state.validation_errors:
            user_prompt = USER_FIX_SQL.format(
                user_query=state.user_query,
                generated_sql=state.generated_sql,
                validation_errors="\n".join(state.validation_errors),
            )
        elif state.golden_sql_hint:
            user_prompt = USER_GENERATE_SQL_WITH_HINT.format(
                user_query=state.user_query,
                golden_sql_hint=state.golden_sql_hint,
            )
        else:
            user_prompt = USER_GENERATE_SQL.format(
                user_query=state.user_query,
            )

        result: GeneratedSQL = await client.chat.completions.create(
            model=settings.llm_model,
            response_model=GeneratedSQL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=settings.llm_temperature,
        )
        return {"generated_sql": result.sql, "validation_errors": []}
    except Exception as e:
        logger.error("generate_sql_node failed: %s", e)
        return {"validation_errors": [f"SQL 生成失败: {e}"]}


async def search_schema_node(state: AgentState) -> dict:
    try:
        client = get_qdrant_client()
        embedder = get_embedder()
        database_hint = state.target_database or None
        if not database_hint and state.intent:
            database_hint = state.intent.get("database_hint")
        tables = await search_tables(
            client,
            embedder,
            state.user_query,
            database_hint=database_hint,
            top_k=10,
        )
        schema_context = "\n".join(t.to_schema_text() for t in tables)
        return {"candidate_tables": tables, "schema_context": schema_context}
    except Exception as e:
        logger.warning("Qdrant 检索失败，尝试本地 catalog 兜底: %s", e)
        from lakequery.catalog import load_local_tables
        tables = load_local_tables()
        if tables:
            schema_context = "\n".join(t.to_schema_text() for t in tables)
            return {"candidate_tables": tables, "schema_context": schema_context}
        return {"validation_errors": [f"Schema 检索失败: {e}"]}


async def validate_sql_node(state: AgentState) -> dict:
    if not state.generated_sql.strip():
        return {
            "validation_errors": state.validation_errors or ["SQL 生成为空，无法校验"],
        }
    try:
        errors = validate_sql(state.generated_sql, state.candidate_tables)
        if not errors:
            with SandboxManager(state.candidate_tables) as conn:
                errors.extend(duckdb_dry_run(conn, state.generated_sql))
        return {"validation_errors": errors}
    except Exception as e:
        logger.error("validate_sql_node failed: %s", e)
        return {"validation_errors": [f"校验过程异常: {e}"]}


async def fix_sql_node(state: AgentState) -> dict:
    try:
        return {"retry_count": state.retry_count + 1}
    except Exception as e:
        logger.error("fix_sql_node failed: %s", e)
        return {"validation_errors": [f"重试计数失败: {e}"]}


async def transpile_sql_node(state: AgentState) -> dict:
    try:
        transpiled = transpile_sql(state.generated_sql, state.target_dialect)
        return {"transpiled_sql": transpiled, "validation_errors": []}
    except Exception as e:
        logger.error("transpile_sql_node failed: %s", e)
        return {"validation_errors": [f"SQL 转译失败: {e}"]}


async def metadata_node(state: AgentState) -> dict:
    """直接从 Qdrant 中已同步的元数据回答关于表结构/数量等问题。"""
    try:
        client = get_qdrant_client()
        embedder = get_embedder()
        database_hint = state.target_database or None

        from qdrant_client.models import FieldCondition, Filter, MatchValue

        query_filter = None
        if database_hint:
            query_filter = Filter(
                must=[
                    FieldCondition(
                        key="database",
                        match=MatchValue(value=database_hint),
                    )
                ]
            )

        query_vector = embedder.encode(state.user_query)
        if hasattr(query_vector, "tolist"):
            query_vector = query_vector.tolist()

        results = await client.query_points(
            collection_name=settings.qdrant_collection,
            query=query_vector,
            query_filter=query_filter,
            limit=200,
        )

        tables = results.points
        db_label = database_hint or "数据湖"
        table_names = sorted(set(
            p.payload.get("table_name", p.payload.get("full_name", "unknown"))
            for p in tables
        ))

        user_q = state.user_query.lower()

        if any(kw in user_q for kw in ["多少", "个数", "数量", "count"]):
            answer = f"{db_label} 中共有 {len(table_names)} 张表。"
        elif any(kw in user_q for kw in ["所有表", "列出", "哪些表", "查看表", "table"]):
            names_str = "、".join(table_names)
            answer = f"{db_label} 中共有 {len(table_names)} 张表：\n{names_str}"
        else:
            names_str = "、".join(table_names[:20])
            suffix = f"等共 {len(table_names)} 张表" if len(table_names) > 20 else ""
            answer = f"{db_label} 中包含以下表：{names_str}{suffix}"

        return {"answer": answer, "status": "success"}
    except Exception as e:
        logger.error("metadata_node failed: %s", e)
        return {"status": "failed", "error_message": f"元数据查询失败: {e}"}


async def respond_node(state: AgentState) -> dict:
    try:
        if state.answer:
            return {"status": "success"}
        if state.status == "failed":
            return {
                "status": "failed",
                "error_message": state.error_message or "处理失败",
            }
        if state.validation_errors or state.retry_count >= state.max_retries:
            return {
                "status": "failed",
                "error_message": "; ".join(state.validation_errors) if state.validation_errors else "超过最大重试次数",
            }
        return {"status": "success"}
    except Exception as e:
        logger.error("respond_node failed: %s", e)
        return {"status": "failed", "error_message": f"响应节点异常: {e}"}
