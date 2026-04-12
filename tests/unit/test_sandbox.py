import duckdb

from lakequery.models.schema import ColumnMeta, TableMeta
from lakequery.sql.sandbox import SandboxManager, duckdb_dry_run, sync_virtual_tables


class TestSandboxManager:
    def test_sandbox_manager_creates_tables(self, sample_tables):
        with SandboxManager(sample_tables) as conn:
            tables = conn.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'trade_dwd' ORDER BY table_name"
            ).fetchall()
            table_names = [r[0] for r in tables]
            assert "dim_product" in table_names
            assert "dim_user" in table_names
            assert "dwd_order_detail" in table_names

    def test_sandbox_manager_blocks_external_access(self, sample_tables):
        with SandboxManager(sample_tables) as conn:
            try:
                conn.execute("SELECT * FROM read_csv_auto('test.csv')")
                assert False, "Should have raised an error"
            except duckdb.Error as e:
                assert "disabled" in str(e).lower() or "permission" in str(e).lower() or "access" in str(e).lower()

    def test_sandbox_manager_closes_connection(self, sample_tables):
        with SandboxManager(sample_tables) as conn:
            conn.execute("SELECT 1")
        # 连接已关闭，再次执行应报错
        try:
            conn.execute("SELECT 1")
            assert False, "Should have raised after close"
        except Exception:
            pass


class TestSyncVirtualTables:
    def test_sync_virtual_tables(self, duckdb_conn, sample_tables):
        sync_virtual_tables(duckdb_conn, sample_tables)

        rows = duckdb_conn.execute(
            "SELECT schema_name FROM information_schema.schemata "
            "WHERE schema_name = 'trade_dwd'"
        ).fetchall()
        assert len(rows) == 1

        tables = duckdb_conn.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'trade_dwd' ORDER BY table_name"
        ).fetchall()
        table_names = [r[0] for r in tables]
        assert "dim_product" in table_names
        assert "dim_user" in table_names
        assert "dwd_order_detail" in table_names

        cols = duckdb_conn.execute(
            "SELECT column_name, data_type FROM information_schema.columns "
            "WHERE table_schema = 'trade_dwd' AND table_name = 'dwd_order_detail' "
            "ORDER BY ordinal_position"
        ).fetchall()
        col_map = {name: dtype for name, dtype in cols}
        assert col_map["order_id"] == "BIGINT"
        assert col_map["amount"] == "DOUBLE"
        assert col_map["status"] == "VARCHAR"
        assert col_map["created_at"] == "TIMESTAMP"
        assert col_map["dt"] == "VARCHAR"

        count = duckdb_conn.execute(
            "SELECT COUNT(*) FROM trade_dwd.dwd_order_detail"
        ).fetchone()[0]
        assert count == 0

    def test_sync_virtual_tables_sql_injection_safe(self, duckdb_conn):
        """恶意表名/列名被正确转义，不会导致 SQL 注入"""
        evil_table = TableMeta(
            catalog="default",
            database="evil_db",
            table_name='foo"; DROP TABLE bar; --',
            columns=[
                ColumnMeta(name='id"; DROP TABLE x; --', data_type="BIGINT"),
                ColumnMeta(name="safe_col", data_type="STRING"),
            ],
            partition_keys=[],
            comment="injection test",
        )
        # 不应抛出异常，表名/列名被 quoted
        sync_virtual_tables(duckdb_conn, [evil_table])

        # 验证表确实被创建（用 information_schema 查询）
        tables = duckdb_conn.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'evil_db'"
        ).fetchall()
        assert len(tables) == 1


class TestDuckdbDryRun:
    def test_duckdb_dry_run_success(self, duckdb_conn, sample_tables):
        sync_virtual_tables(duckdb_conn, sample_tables)

        sql = (
            "SELECT status, COUNT(*) AS cnt, SUM(amount) AS total "
            "FROM trade_dwd.dwd_order_detail "
            "WHERE dt = '20260301' "
            "GROUP BY status"
        )
        errors = duckdb_dry_run(duckdb_conn, sql)
        assert errors == []

    def test_duckdb_dry_run_syntax_error(self, duckdb_conn, sample_tables):
        sync_virtual_tables(duckdb_conn, sample_tables)

        sql = "SELECTT * FORM trade_dwd.dwd_order_detail"
        errors = duckdb_dry_run(duckdb_conn, sql)
        assert len(errors) == 1
        assert "DuckDB dry-run 失败" in errors[0]

    def test_duckdb_dry_run_table_not_found(self, duckdb_conn, sample_tables):
        sync_virtual_tables(duckdb_conn, sample_tables)

        sql = "SELECT * FROM trade_dwd.non_existent_table"
        errors = duckdb_dry_run(duckdb_conn, sql)
        assert len(errors) == 1
        assert "DuckDB dry-run 失败" in errors[0]
