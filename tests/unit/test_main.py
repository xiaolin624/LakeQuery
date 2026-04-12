from unittest.mock import AsyncMock, patch

import pytest

from lakequery.main import ensure_collections

PATCH_QDRANT = "lakequery.agent.nodes.get_qdrant_client"


class TestEnsureCollections:
    @pytest.mark.asyncio
    async def test_creates_missing_collections(self):
        mock_client = AsyncMock()
        mock_client.collection_exists = AsyncMock(return_value=False)
        mock_client.create_collection = AsyncMock()

        with patch(PATCH_QDRANT, return_value=mock_client):
            await ensure_collections()

        assert mock_client.create_collection.call_count == 2
        created_names = [
            call.kwargs["collection_name"]
            for call in mock_client.create_collection.call_args_list
        ]
        assert "table_schemas" in created_names
        assert "golden_queries" in created_names

    @pytest.mark.asyncio
    async def test_skips_existing_collections(self):
        mock_client = AsyncMock()
        mock_client.collection_exists = AsyncMock(return_value=True)

        with patch(PATCH_QDRANT, return_value=mock_client):
            await ensure_collections()

        mock_client.create_collection.assert_not_called()

    @pytest.mark.asyncio
    async def test_handles_qdrant_connection_failure(self):
        mock_client = AsyncMock()
        mock_client.collection_exists = AsyncMock(side_effect=ConnectionError("refused"))

        with patch(PATCH_QDRANT, return_value=mock_client):
            await ensure_collections()  # 不应抛异常

        mock_client.create_collection.assert_not_called()
