from unittest.mock import AsyncMock, patch

import pytest

from lakequery.agent.graph import build_graph
from lakequery.models.query import GeneratedSQL, ParsedIntent
from lakequery.models.state import AgentState

GOLDEN_SQL = (
    "SELECT status, COUNT(DISTINCT user_id) AS dau "
    "FROM trade_dwd.dwd_order_detail "
    "WHERE dt = '20260409' "
    "GROUP BY status ORDER BY dau DESC"
)


class TestGraphHappyPath:
    @pytest.mark.asyncio
    async def test_graph_happy_path(self, mock_instructor_client, sample_tables):
        """LLM 一次性生成正确 SQL，完整流程走通"""
        # mock 返回的 SQL 引用了已知表和列，能通过 validator
        mock_instructor_client._next_generated_sql = GeneratedSQL(
            sql=(
                "SELECT status, COUNT(DISTINCT user_id) AS dau "
                "FROM trade_dwd.dwd_order_detail "
                "WHERE dt = '20260409' "
                "GROUP BY status ORDER BY dau DESC"
            ),
            reasoning="按状态统计DAU",
            tables_used=["trade_dwd.dwd_order_detail"],
            partition_filters=["dt = '20260409'"],
        )

        compiled = build_graph().compile()
        initial_state = AgentState(
            user_query="查下昨天各省的DAU",
            candidate_tables=sample_tables,
        )
        with patch("lakequery.agent.nodes.search_tables", return_value=sample_tables):
            result = await compiled.ainvoke(initial_state)

        assert result["status"] == "success"
        assert result["transpiled_sql"] != ""
        assert result["retry_count"] == 0
        assert result["validation_errors"] == []


class TestGraphFixLoop:
    @pytest.mark.asyncio
    async def test_graph_fix_loop(self, mock_instructor_client, sample_tables):
        """LLM 第一次生成错误 SQL（未知列），第二次修正成功"""
        call_count = 0
        bad_sql = GeneratedSQL(
            sql="SELECT fake_col FROM trade_dwd.dwd_order_detail WHERE dt = '20260409'",
            reasoning="first attempt",
            tables_used=["trade_dwd.dwd_order_detail"],
            partition_filters=["dt = '20260409'"],
        )
        good_sql = GeneratedSQL(
            sql=(
                "SELECT status, COUNT(DISTINCT user_id) AS dau "
                "FROM trade_dwd.dwd_order_detail "
                "WHERE dt = '20260409' "
                "GROUP BY status"
            ),
            reasoning="fixed",
            tables_used=["trade_dwd.dwd_order_detail"],
            partition_filters=["dt = '20260409'"],
        )

        def side_effect(**kwargs):
            nonlocal call_count
            response_model = kwargs.get("response_model")
            if response_model is ParsedIntent:
                return mock_instructor_client._next_parsed_intent
            if response_model is GeneratedSQL:
                call_count += 1
                return bad_sql if call_count == 1 else good_sql
            raise ValueError(f"Unexpected response_model: {response_model}")

        mock_instructor_client.chat.completions.create.side_effect = side_effect

        compiled = build_graph().compile()
        initial_state = AgentState(
            user_query="查下昨天各省的DAU",
            candidate_tables=sample_tables,
        )
        with patch("lakequery.agent.nodes.search_tables", return_value=sample_tables):
            result = await compiled.ainvoke(initial_state)

        assert result["status"] == "success"
        assert result["retry_count"] == 1
        assert "fake_col" not in result["transpiled_sql"]


class TestGraphMaxRetriesFailed:
    @pytest.mark.asyncio
    async def test_graph_max_retries_failed(self, mock_instructor_client, sample_tables):
        """LLM 持续生成错误 SQL，达到最大重试次数后失败"""
        # 始终返回包含未知列的 SQL
        mock_instructor_client._next_generated_sql = GeneratedSQL(
            sql="SELECT fake_col FROM trade_dwd.dwd_order_detail WHERE dt = '20260409'",
            reasoning="always wrong",
            tables_used=["trade_dwd.dwd_order_detail"],
            partition_filters=["dt = '20260409'"],
        )

        def side_effect(**kwargs):
            response_model = kwargs.get("response_model")
            if response_model is ParsedIntent:
                return mock_instructor_client._next_parsed_intent
            if response_model is GeneratedSQL:
                return mock_instructor_client._next_generated_sql
            raise ValueError(f"Unexpected response_model: {response_model}")

        mock_instructor_client.chat.completions.create.side_effect = side_effect

        compiled = build_graph().compile()
        initial_state = AgentState(
            user_query="查下昨天各省的DAU",
            candidate_tables=sample_tables,
            max_retries=3,
        )
        with patch("lakequery.agent.nodes.search_tables", return_value=sample_tables):
            result = await compiled.ainvoke(initial_state)

        assert result["status"] == "failed"
        assert result["retry_count"] >= 3


class TestGraphParseIntentFailure:
    @pytest.mark.asyncio
    async def test_graph_short_circuits_on_intent_failure(self, mock_instructor_client, sample_tables):
        """parse_intent 失败时，图直接进入 respond 节点，不继续后续流程"""
        mock_instructor_client.chat.completions.create = AsyncMock(
            side_effect=RuntimeError("API key invalid"),
        )

        compiled = build_graph().compile()
        initial_state = AgentState(user_query="查下昨天各省的DAU")
        result = await compiled.ainvoke(initial_state)

        assert result["status"] == "failed"
        assert "意图解析失败" in result["error_message"]
        # 不应走到 generate_sql，所以 generated_sql 为空
        assert result["generated_sql"] == ""


class TestGraphGoldenQueryHit:
    @pytest.mark.asyncio
    async def test_graph_golden_query_hit(self, mock_instructor_client, sample_tables):
        """黄金查询命中后作为 few-shot 注入 prompt，仍然走完整 LLM 生成流程"""
        mock_instructor_client._next_generated_sql = GeneratedSQL(
            sql=GOLDEN_SQL,
            reasoning="参考历史查询生成",
            tables_used=["trade_dwd.dwd_order_detail"],
            partition_filters=["dt = '20260409'"],
        )

        compiled = build_graph().compile()
        initial_state = AgentState(
            user_query="查下昨天各省的DAU",
            candidate_tables=sample_tables,
        )

        with (
            patch(
                "lakequery.agent.nodes.search_golden_query",
                new_callable=AsyncMock,
                return_value=GOLDEN_SQL,
            ) as mock_search_golden,
            patch("lakequery.agent.nodes.search_tables", return_value=sample_tables),
        ):
            result = await compiled.ainvoke(initial_state)

        assert result["status"] == "success"
        assert result["is_golden_hit"] is True
        assert result["golden_sql_hint"] == GOLDEN_SQL
        assert result["retry_count"] == 0
        # 黄金查询不跳过 LLM，LLM create 被调用（parse_intent + generate_sql 至少 2 次）
        assert mock_instructor_client.chat.completions.create.call_count >= 2
        assert result["transpiled_sql"] != ""
