from lakequery.models.schema import TableMeta
from lakequery.models.state import AgentState


class TestAgentStateDefaults:
    def test_default_values(self):
        state = AgentState()
        assert state.user_query == ""
        assert state.target_dialect == "hive"
        assert state.conversation_id == ""
        assert state.intent is None
        assert state.candidate_tables == []
        assert state.schema_context == ""
        assert state.generated_sql == ""
        assert state.transpiled_sql == ""
        assert state.validation_errors == []
        assert state.retry_count == 0
        assert state.max_retries == 3
        assert state.status == "pending"
        assert state.execution_result is None
        assert state.error_message == ""

    def test_custom_initialization(self):
        state = AgentState(
            user_query="查一下订单数",
            target_dialect="spark",
            max_retries=5,
        )
        assert state.user_query == "查一下订单数"
        assert state.target_dialect == "spark"
        assert state.max_retries == 5
        assert state.status == "pending"

    def test_candidate_tables_typing(self, sample_tables: list[TableMeta]):
        state = AgentState(
            user_query="测试",
            candidate_tables=sample_tables,
        )
        assert len(state.candidate_tables) == 3
        assert state.candidate_tables[0].full_name == "trade_dwd.dwd_order_detail"
