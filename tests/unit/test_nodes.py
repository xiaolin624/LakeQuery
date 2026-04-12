from unittest.mock import patch

import pytest

from lakequery.agent.nodes import (
    generate_sql_node,
    parse_intent_node,
    validate_sql_node,
)
from lakequery.models.query import GeneratedSQL, ParsedIntent
from lakequery.models.state import AgentState


class TestParseIntentNode:
    @pytest.mark.asyncio
    async def test_parse_intent_node_clear(self, mock_instructor_client):
        state = AgentState(user_query="查下昨天各省的DAU")
        result = await parse_intent_node(state)

        assert result["intent"] is not None
        assert result["intent"]["ambiguous"] is False
        assert result["intent"]["time_range"] == "昨天"
        assert "province" in result["intent"]["dimensions"]
        assert "DAU" in result["intent"]["metrics"]
        mock_instructor_client.chat.completions.create.assert_called_once()

    @pytest.mark.asyncio
    async def test_parse_intent_node_ambiguous(self, mock_instructor_client):
        mock_instructor_client._next_parsed_intent = ParsedIntent(
            ambiguous=True,
            clarification_question='请问您说的"活跃用户"是指日活(DAU)还是月活(MAU)？',
        )
        state = AgentState(user_query="查一下活跃用户")
        result = await parse_intent_node(state)

        assert result["intent"] is not None
        assert result["intent"]["ambiguous"] is True
        assert "DAU" in result["intent"]["clarification_question"]

    @pytest.mark.asyncio
    async def test_parse_intent_node_exception(self):
        state = AgentState(user_query="查一下活跃用户")
        with patch("lakequery.agent.nodes.get_llm_client", side_effect=RuntimeError("llm down")):
            result = await parse_intent_node(state)

        assert result["status"] == "failed"
        assert "意图解析失败" in result["error_message"]


class TestGenerateSqlNode:
    @pytest.mark.asyncio
    async def test_generate_sql_node_success(self, mock_instructor_client, sample_tables):
        state = AgentState(
            user_query="查下昨天各省的DAU",
            intent={
                "time_range": "昨天",
                "dimensions": ["province"],
                "metrics": ["DAU"],
                "filters": [],
                "sort": "DAU DESC",
                "ambiguous": False,
                "clarification_question": "",
            },
            candidate_tables=sample_tables,
            schema_context="\n".join(t.to_schema_text() for t in sample_tables),
        )
        result = await generate_sql_node(state)

        assert result["generated_sql"] != ""
        assert result["validation_errors"] == []
        assert "SELECT" in result["generated_sql"]
        assert "trade_dwd.dwd_order_detail" in result["generated_sql"]
        mock_instructor_client.chat.completions.create.assert_called_once()

    @pytest.mark.asyncio
    async def test_generate_sql_node_with_errors(self, mock_instructor_client, sample_tables):
        mock_instructor_client._next_generated_sql = GeneratedSQL(
            sql="SELECT province, COUNT(DISTINCT user_id) AS dau FROM trade_dwd.dwd_order_detail WHERE dt = '20260409' GROUP BY province",
            reasoning="修正了之前的列名错误",
            tables_used=["trade_dwd.dwd_order_detail"],
            partition_filters=["dt = '20260409'"],
        )
        state = AgentState(
            user_query="查下昨天各省的DAU",
            intent={
                "time_range": "昨天",
                "dimensions": ["province"],
                "metrics": ["DAU"],
                "filters": [],
                "sort": None,
                "ambiguous": False,
                "clarification_question": "",
            },
            candidate_tables=sample_tables,
            schema_context="\n".join(t.to_schema_text() for t in sample_tables),
            generated_sql="SELECT provincee FROM trade_dwd.dwd_order_detail",
            validation_errors=["表 trade_dwd.dwd_order_detail 中未找到列: provincee"],
            retry_count=1,
        )
        result = await generate_sql_node(state)

        assert result["generated_sql"] != ""
        assert "provincee" not in result["generated_sql"]
        # 验证调用时 messages 中包含了错误信息（使用了 FIX prompt）
        call_kwargs = mock_instructor_client.chat.completions.create.call_args
        messages = call_kwargs.kwargs.get("messages") or call_kwargs[1].get("messages")
        user_msg = messages[-1]["content"]
        assert "provincee" in user_msg
        assert "修正" in user_msg or "错误" in user_msg

    @pytest.mark.asyncio
    async def test_generate_sql_node_exception(self, sample_tables):
        state = AgentState(
            user_query="查下昨天各省的DAU",
            candidate_tables=sample_tables,
            schema_context="\n".join(t.to_schema_text() for t in sample_tables),
        )
        with patch("lakequery.agent.nodes.get_llm_client", side_effect=RuntimeError("llm timeout")):
            result = await generate_sql_node(state)

        assert len(result["validation_errors"]) == 1
        assert "SQL 生成失败" in result["validation_errors"][0]


class TestValidateSqlNode:
    @pytest.mark.asyncio
    async def test_validate_sql_node_happy_path(self, sample_tables):
        state = AgentState(
            generated_sql=(
                "SELECT status, COUNT(*) AS cnt "
                "FROM trade_dwd.dwd_order_detail "
                "WHERE dt = '20260301' "
                "GROUP BY status"
            ),
            candidate_tables=sample_tables,
        )
        result = await validate_sql_node(state)
        assert result["validation_errors"] == []

    @pytest.mark.asyncio
    async def test_validate_sql_node_includes_dry_run_errors(self, sample_tables):
        state = AgentState(
            generated_sql="SELECT status FROM trade_dwd.dwd_order_detail WHERE dt = '20260301'",
            candidate_tables=sample_tables,
        )
        with patch("lakequery.agent.nodes.duckdb_dry_run", return_value=["DuckDB dry-run 失败: mock"]):
            result = await validate_sql_node(state)
        assert result["validation_errors"] == ["DuckDB dry-run 失败: mock"]

    @pytest.mark.asyncio
    async def test_validate_sql_node_exception(self, sample_tables):
        state = AgentState(
            generated_sql="SELECT status FROM trade_dwd.dwd_order_detail",
            candidate_tables=sample_tables,
        )
        with patch("lakequery.agent.nodes.validate_sql", side_effect=RuntimeError("validator crash")):
            result = await validate_sql_node(state)
        assert len(result["validation_errors"]) == 1
        assert "校验过程异常" in result["validation_errors"][0]

    @pytest.mark.asyncio
    async def test_validate_sql_node_empty_sql_preserves_errors(self):
        """generated_sql 为空时，不覆盖已有的 validation_errors"""
        state = AgentState(
            generated_sql="",
            validation_errors=["SQL 生成失败: llm timeout"],
        )
        result = await validate_sql_node(state)
        assert "SQL 生成失败" in result["validation_errors"][0]
        assert "语法解析" not in str(result["validation_errors"])

    @pytest.mark.asyncio
    async def test_validate_sql_node_empty_sql_no_prior_errors(self):
        """generated_sql 为空且无前置错误时，返回明确提示"""
        state = AgentState(generated_sql="", validation_errors=[])
        result = await validate_sql_node(state)
        assert "SQL 生成为空" in result["validation_errors"][0]
