import pytest

from lakequery.rag.indexer import index_tables
from lakequery.rag.retriever import search_tables


@pytest.mark.asyncio
async def test_index_tables_inserts_all(sample_tables, mock_embedder, qdrant_memory):
    await index_tables(qdrant_memory, mock_embedder, sample_tables)
    info = await qdrant_memory.get_collection("table_schemas")
    assert info.points_count == len(sample_tables)


@pytest.mark.asyncio
async def test_index_tables_idempotent(sample_tables, mock_embedder, qdrant_memory):
    await index_tables(qdrant_memory, mock_embedder, sample_tables)
    await index_tables(qdrant_memory, mock_embedder, sample_tables)
    info = await qdrant_memory.get_collection("table_schemas")
    assert info.points_count == len(sample_tables)


@pytest.mark.asyncio
async def test_index_tables_stores_payload(sample_tables, mock_embedder, qdrant_memory):
    await index_tables(qdrant_memory, mock_embedder, sample_tables)
    results = await qdrant_memory.scroll(collection_name="table_schemas", limit=10)
    points = results[0]
    payloads = {p.payload["full_name"] for p in points}
    expected = {t.full_name for t in sample_tables}
    assert payloads == expected


@pytest.mark.asyncio
async def test_search_tables_returns_results(sample_tables, mock_embedder, qdrant_memory):
    await index_tables(qdrant_memory, mock_embedder, sample_tables)
    tables = await search_tables(qdrant_memory, mock_embedder, "查询订单金额", top_k=3)
    assert len(tables) <= 3
    assert len(tables) > 0
    assert all(hasattr(t, "full_name") for t in tables)


@pytest.mark.asyncio
async def test_search_tables_with_db_filter(sample_tables, mock_embedder, qdrant_memory):
    await index_tables(qdrant_memory, mock_embedder, sample_tables)
    tables = await search_tables(
        qdrant_memory, mock_embedder, "查询订单", database_hint="trade_dwd", top_k=5
    )
    assert all(t.database == "trade_dwd" for t in tables)


@pytest.mark.asyncio
async def test_search_tables_empty_collection(mock_embedder, qdrant_memory):
    tables = await search_tables(qdrant_memory, mock_embedder, "查询订单", top_k=5)
    assert tables == []
