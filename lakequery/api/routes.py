import asyncio
import logging

from fastapi import APIRouter, HTTPException

from lakequery.agent.graph import graph
from lakequery.agent.nodes import get_embedder, get_qdrant_client
from lakequery.catalog import HMSClient, IcebergClient
from lakequery.config import settings
from lakequery.models.query import (
    CatalogSyncRequest,
    CatalogSyncResponse,
    ColumnMetaResponse,
    GoldenQueryRequest,
    GoldenQueryResponse,
    HealthResponse,
    QueryRequest,
    QueryResponse,
    TableMetaResponse,
)
from lakequery.models.state import AgentState
from lakequery.rag import index_tables, save_golden_query

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1")


@router.get("/health", response_model=HealthResponse)
async def health():
    return HealthResponse(
        status="ok",
        catalogs_connected=[],
        vector_store_count=0,
    )


@router.post("/query", response_model=QueryResponse)
async def query(request: QueryRequest):
    try:
        initial_state = AgentState(
            user_query=request.question,
            target_dialect=request.dialect,
            target_database=request.database,
        )

        result = await graph.ainvoke(initial_state)

        generated_sql = result.get("transpiled_sql", "") or result.get("generated_sql", "")
        validation_errors = result.get("validation_errors", [])
        status = result.get("status", "pending")
        error_message = result.get("error_message", "")
        answer = result.get("answer", "") or None

        candidate_tables = result.get("candidate_tables", [])
        tables_used = [
            t.full_name if hasattr(t, "full_name") else t.get("full_name", "")
            for t in candidate_tables
        ]

        return QueryResponse(
            sql=generated_sql if status == "success" else "",
            dialect=request.dialect,
            tables_used=tables_used,
            validation_passed=(status == "success" and not validation_errors),
            retry_count=result.get("retry_count", 0),
            execution_result=result.get("execution_result"),
            error=error_message if status == "failed" else None,
            answer=answer,
        )
    except Exception as e:
        logger.error("query endpoint error: %s", e)
        return QueryResponse(
            sql="",
            dialect=request.dialect,
            tables_used=[],
            validation_passed=False,
            retry_count=0,
            error=f"服务内部错误: {e}",
        )


@router.post("/catalog/sync", response_model=CatalogSyncResponse)
async def catalog_sync(request: CatalogSyncRequest):
    try:
        if request.catalog_type == "iceberg":
            if not request.iceberg_rest_uri:
                raise HTTPException(status_code=400, detail="Iceberg REST URI 未配置，请提供 iceberg_rest_uri 参数")
            client = IcebergClient(catalog_name="default", rest_uri=request.iceberg_rest_uri)
        else:
            hms_host = request.hms_host or settings.hms_host
            if not hms_host:
                raise HTTPException(status_code=400, detail="HMS host 未配置，请提供 hms_host 参数或设置 LQ_HMS_HOST 环境变量")
            hms_port = request.hms_port or settings.hms_port
            client = HMSClient(host=hms_host, port=hms_port, auth=request.hms_auth, username=request.hms_username)

        tables = await asyncio.to_thread(client.fetch_database_schema, request.database)
        if not tables:
            return CatalogSyncResponse(tables_synced=0, vectors_indexed=0, table_names=[])

        qdrant = get_qdrant_client()
        embedder = get_embedder()
        await index_tables(qdrant, embedder, tables)

        table_responses = [
            TableMetaResponse(
                table_name=t.table_name,
                database=t.database,
                columns=[
                    ColumnMetaResponse(
                        name=c.name,
                        data_type=c.data_type,
                        is_partition_key=c.is_partition_key,
                        comment=c.comment,
                    )
                    for c in t.columns
                ],
            )
            for t in tables
        ]

        return CatalogSyncResponse(
            tables_synced=len(tables),
            vectors_indexed=len(tables),
            table_names=[t.full_name for t in tables],
            tables=table_responses,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error("catalog sync error: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"同步失败: {e}") from e


@router.post("/golden-queries", response_model=GoldenQueryResponse)
async def create_golden_query(request: GoldenQueryRequest):
    qdrant = get_qdrant_client()
    embedder = get_embedder()
    await save_golden_query(qdrant, embedder, request.question, request.sql)
    return GoldenQueryResponse(status="ok")
