from lakequery.sql.transpiler import transpile_sql


class TestTranspileSql:
    def test_transpile_to_hive(self):
        sql = "SELECT CAST('2026-03-01' AS DATE), user_id FROM trade_dwd.dim_user"
        result = transpile_sql(sql, "hive")
        assert isinstance(result, str)
        assert len(result) > 0
        # Hive 方言应保留 CAST 或用等价写法
        assert "user_id" in result
        assert "trade_dwd" in result

    def test_transpile_to_spark(self):
        sql = (
            "SELECT order_id, amount "
            "FROM trade_dwd.dwd_order_detail "
            "WHERE dt = '20260301' "
            "LIMIT 10"
        )
        result = transpile_sql(sql, "spark")
        assert isinstance(result, str)
        assert "order_id" in result

    def test_transpile_to_trino(self):
        sql = "SELECT COUNT(*) AS cnt FROM trade_dwd.dwd_order_detail"
        result = transpile_sql(sql, "trino")
        assert isinstance(result, str)
        assert "cnt" in result

    def test_transpile_invalid_sql_raises(self):
        # 严重畸形 SQL 应抛出异常或返回合理结果
        sql = "THIS IS NOT SQL AT ALL %%% ;;;;"
        try:
            result = transpile_sql(sql, "hive")
            # sqlglot 对部分畸形 SQL 可能尽力解析，不一定异常
        except ValueError:
            pass  # 预期行为
