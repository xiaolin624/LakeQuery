from lakequery.catalog.local import load_local_tables


class TestLoadLocalTables:
    def test_load_local_tables_returns_tables(self):
        tables = load_local_tables()
        assert len(tables) == 3
        names = [t.full_name for t in tables]
        assert "trade_dwd.dwd_order_detail" in names
        assert "trade_dwd.dim_user" in names
        assert "trade_dwd.dim_product" in names

    def test_load_local_tables_columns(self):
        tables = load_local_tables()
        order_table = [t for t in tables if t.table_name == "dwd_order_detail"][0]
        col_names = [c.name for c in order_table.columns]
        assert "order_id" in col_names
        assert "dt" in col_names
        assert order_table.partition_keys == ["dt"]

    def test_load_local_tables_to_schema_text(self):
        tables = load_local_tables()
        for t in tables:
            text = t.to_schema_text()
            assert t.full_name in text
