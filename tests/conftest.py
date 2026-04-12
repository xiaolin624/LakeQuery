import duckdb
import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from qdrant_client import AsyncQdrantClient
from qdrant_client.models import Distance, VectorParams

from lakequery.models.schema import ColumnMeta, TableMeta
from lakequery.models.query import ParsedIntent, GeneratedSQL


@pytest.fixture
def sample_tables() -> list[TableMeta]:
    """电商场景典型表元数据 fixture，含分区表和无分区表"""
    order_table = TableMeta(
        catalog="default",
        database="trade_dwd",
        table_name="dwd_order_detail",
        columns=[
            ColumnMeta(name="order_id", data_type="BIGINT", comment="订单ID"),
            ColumnMeta(name="user_id", data_type="BIGINT", comment="用户ID"),
            ColumnMeta(name="product_id", data_type="BIGINT", comment="商品ID"),
            ColumnMeta(name="amount", data_type="DOUBLE", comment="订单金额"),
            ColumnMeta(name="status", data_type="STRING", comment="订单状态"),
            ColumnMeta(name="created_at", data_type="TIMESTAMP", comment="下单时间"),
            ColumnMeta(
                name="dt",
                data_type="STRING",
                comment="日期分区",
                is_partition_key=True,
            ),
        ],
        partition_keys=["dt"],
        comment="订单明细宽表",
        storage_format="Parquet",
        location="s3://warehouse/trade_dwd/dwd_order_detail",
    )

    user_table = TableMeta(
        catalog="default",
        database="trade_dwd",
        table_name="dim_user",
        columns=[
            ColumnMeta(name="user_id", data_type="BIGINT", comment="用户ID"),
            ColumnMeta(name="username", data_type="STRING", comment="用户名"),
            ColumnMeta(name="gender", data_type="STRING", comment="性别"),
            ColumnMeta(name="province", data_type="STRING", comment="省份"),
            ColumnMeta(name="register_date", data_type="DATE", comment="注册日期"),
        ],
        partition_keys=[],
        comment="用户维度表",
        storage_format="ORC",
        location="s3://warehouse/trade_dwd/dim_user",
    )

    product_table = TableMeta(
        catalog="default",
        database="trade_dwd",
        table_name="dim_product",
        columns=[
            ColumnMeta(name="product_id", data_type="BIGINT", comment="商品ID"),
            ColumnMeta(name="product_name", data_type="STRING", comment="商品名称"),
            ColumnMeta(name="category", data_type="STRING", comment="商品类目"),
            ColumnMeta(name="price", data_type="DOUBLE", comment="商品单价"),
            ColumnMeta(name="brand", data_type="STRING", comment="品牌"),
        ],
        partition_keys=[],
        comment="商品维度表",
        storage_format="ORC",
        location="s3://warehouse/trade_dwd/dim_product",
    )

    return [order_table, user_table, product_table]


@pytest.fixture
def duckdb_conn():
    conn = duckdb.connect(":memory:")
    conn.execute("SET enable_external_access = false")
    conn.execute("SET enable_object_cache = false")
    yield conn
    conn.close()


@pytest.fixture
def mock_instructor_client():
    mock_client = MagicMock()

    async def _create_response(**kwargs):
        response_model = kwargs.get("response_model")
        if response_model is ParsedIntent:
            return mock_client._next_parsed_intent
        if response_model is GeneratedSQL:
            return mock_client._next_generated_sql
        raise ValueError(f"Unexpected response_model: {response_model}")

    mock_client.chat.completions.create = AsyncMock(side_effect=_create_response)

    # 预设默认返回值
    mock_client._next_parsed_intent = ParsedIntent(
        time_range="昨天",
        dimensions=["province"],
        metrics=["DAU"],
        filters=[],
        sort="DAU DESC",
        ambiguous=False,
        clarification_question="",
    )
    mock_client._next_generated_sql = GeneratedSQL(
        sql="SELECT province, COUNT(DISTINCT user_id) AS dau FROM trade_dwd.dwd_order_detail WHERE dt = '20260409' GROUP BY province ORDER BY dau DESC",
        reasoning="根据用户需求按省份统计DAU",
        tables_used=["trade_dwd.dwd_order_detail"],
        partition_filters=["dt = '20260409'"],
    )

    with patch("lakequery.agent.nodes.get_llm_client", return_value=mock_client):
        yield mock_client


MOCK_EMBED_DIM = 1024


@pytest.fixture
def mock_embedder():
    embedder = MagicMock()
    embedder.encode.return_value = [0.1] * MOCK_EMBED_DIM
    return embedder


@pytest_asyncio.fixture
async def qdrant_memory():
    client = AsyncQdrantClient(location=":memory:", check_compatibility=False)
    await client.create_collection(
        collection_name="table_schemas",
        vectors_config=VectorParams(size=MOCK_EMBED_DIM, distance=Distance.COSINE),
    )
    yield client
    await client.close()
