from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from lakequery.main import app
from lakequery.models.schema import ColumnMeta, TableMeta
from lakequery.models.query import GoldenQueryRequest


@pytest.fixture
def mock_graph_ainvoke():
    """Mock graph.ainvoke 返回成功的状态 dict（LangGraph 返回 dict）"""
    success_result = {
        "user_query": "查下昨天各省的DAU",
        "generated_sql": "SELECT province, COUNT(DISTINCT user_id) AS dau FROM trade_dwd.dwd_order_detail WHERE dt = '20260410' GROUP BY province",
        "transpiled_sql": "SELECT province, COUNT(DISTINCT user_id) AS dau FROM trade_dwd.dwd_order_detail WHERE dt = '20260410' GROUP BY province",
        "validation_errors": [],
        "retry_count": 0,
        "status": "success",
        "target_dialect": "hive",
        "error_message": "",
        "candidate_tables": [],
    }
    with patch("lakequery.api.routes.graph") as mock_graph:
        mock_graph.ainvoke = AsyncMock(return_value=success_result)
        yield mock_graph


@pytest.fixture
def mock_graph_ainvoke_failed():
    """Mock graph.ainvoke 返回失败的状态 dict"""
    failed_result = {
        "user_query": "模糊查询",
        "generated_sql": "",
        "transpiled_sql": "",
        "validation_errors": ["SQL 生成失败"],
        "retry_count": 3,
        "status": "failed",
        "error_message": "超过最大重试次数",
        "candidate_tables": [],
    }
    with patch("lakequery.api.routes.graph") as mock_graph:
        mock_graph.ainvoke = AsyncMock(return_value=failed_result)
        yield mock_graph


class TestHealthEndpoint:
    async def test_health_returns_ok(self):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.get("/api/v1/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "catalogs_connected" in data
        assert "vector_store_count" in data


class TestQueryEndpoint:
    async def test_query_success(self, mock_graph_ainvoke):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.post("/api/v1/query", json={
                "question": "查下昨天各省的DAU",
                "dialect": "hive",
            })
        assert resp.status_code == 200
        data = resp.json()
        assert data["sql"] != ""
        assert data["validation_passed"] is True
        assert data["retry_count"] == 0
        assert data["error"] is None

    async def test_query_failed(self, mock_graph_ainvoke_failed):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.post("/api/v1/query", json={
                "question": "模糊查询",
            })
        assert resp.status_code == 200
        data = resp.json()
        assert data["sql"] == ""
        assert data["validation_passed"] is False
        assert data["error"] is not None

    async def test_query_missing_question_returns_422(self):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.post("/api/v1/query", json={})
        assert resp.status_code == 422

    async def test_query_graph_exception_returns_error(self):
        """graph.ainvoke 抛异常时，/query 不返回 500 而是返回带 error 字段的 200"""
        with patch("lakequery.api.routes.graph") as mock_graph:
            mock_graph.ainvoke = AsyncMock(side_effect=RuntimeError("graph exploded"))
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                resp = await ac.post("/api/v1/query", json={
                    "question": "test",
                })
        assert resp.status_code == 200
        data = resp.json()
        assert data["sql"] == ""
        assert data["error"] is not None
        assert "服务内部错误" in data["error"]


class TestCatalogSyncEndpoint:
    async def test_catalog_sync_success(self):
        mock_tables = [
            TableMeta(
                catalog="default",
                database="trade_dwd",
                table_name="dwd_order_detail",
                columns=[ColumnMeta(name="order_id", data_type="bigint")],
            ),
        ]
        with (
            patch("lakequery.api.routes.HMSClient") as MockHMS,
            patch("lakequery.api.routes.get_qdrant_client") as mock_qdrant,
            patch("lakequery.api.routes.get_embedder") as mock_embedder,
            patch("lakequery.api.routes.index_tables", new_callable=AsyncMock) as mock_index,
        ):
            MockHMS.return_value.fetch_database_schema.return_value = mock_tables
            mock_qdrant.return_value = MagicMock()
            mock_embedder.return_value = MagicMock()

            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                resp = await ac.post("/api/v1/catalog/sync", json={
                    "database": "trade_dwd",
                    "hms_host": "fake-hive",
                })
            assert resp.status_code == 200
            data = resp.json()
            assert data["tables_synced"] == 1
            assert data["vectors_indexed"] == 1
            assert "trade_dwd.dwd_order_detail" in data["table_names"]
            assert len(data["tables"]) == 1
            assert data["tables"][0]["table_name"] == "dwd_order_detail"
            assert data["tables"][0]["database"] == "trade_dwd"
            assert len(data["tables"][0]["columns"]) == 1
            mock_index.assert_called_once()

    async def test_catalog_sync_no_host_returns_400(self):
        with patch("lakequery.api.routes.settings") as mock_settings:
            mock_settings.hms_host = ""
            mock_settings.hms_port = 10000
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                resp = await ac.post("/api/v1/catalog/sync", json={
                    "database": "trade_dwd",
                })
            assert resp.status_code == 400


class TestGoldenQueryEndpoint:
    async def test_save_golden_query_success(self):
        with (
            patch("lakequery.api.routes.get_qdrant_client") as mock_qdrant,
            patch("lakequery.api.routes.get_embedder") as mock_embedder,
            patch("lakequery.api.routes.save_golden_query", new_callable=AsyncMock) as mock_save,
        ):
            mock_qdrant.return_value = MagicMock()
            mock_embedder.return_value = MagicMock()

            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                resp = await ac.post("/api/v1/golden-queries", json={
                    "question": "查下昨天各省的DAU",
                    "sql": "SELECT province, COUNT(DISTINCT user_id) AS dau FROM trade_dwd.dwd_order_detail WHERE dt = '20260410' GROUP BY province",
                })
            assert resp.status_code == 200
            data = resp.json()
            assert data["status"] == "ok"
            mock_save.assert_called_once()

    async def test_save_golden_query_missing_fields_returns_422(self):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.post("/api/v1/golden-queries", json={"question": "只有问题没有SQL"})
        assert resp.status_code == 422
