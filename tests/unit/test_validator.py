import pytest

from lakequery.models.schema import TableMeta
from lakequery.sql.validator import validate_sql


class TestValidateSqlRejectsNonSelect:
    def test_rejects_insert(self, sample_tables):
        sql = "INSERT INTO trade_dwd.dwd_order_detail (order_id) VALUES (1)"
        errors = validate_sql(sql, sample_tables)
        assert len(errors) >= 1
        assert any("SELECT" in e or "禁止" in e or "不允许" in e for e in errors)

    def test_rejects_drop(self, sample_tables):
        sql = "DROP TABLE trade_dwd.dwd_order_detail"
        errors = validate_sql(sql, sample_tables)
        assert len(errors) >= 1
        assert any("SELECT" in e or "禁止" in e or "不允许" in e for e in errors)

    def test_rejects_delete(self, sample_tables):
        sql = "DELETE FROM trade_dwd.dwd_order_detail WHERE order_id = 1"
        errors = validate_sql(sql, sample_tables)
        assert len(errors) >= 1

    def test_rejects_update(self, sample_tables):
        sql = "UPDATE trade_dwd.dwd_order_detail SET status = 'X' WHERE order_id = 1"
        errors = validate_sql(sql, sample_tables)
        assert len(errors) >= 1

    def test_rejects_create(self, sample_tables):
        sql = "CREATE TABLE trade_dwd.hack (id INT)"
        errors = validate_sql(sql, sample_tables)
        assert len(errors) >= 1

    def test_rejects_alter(self, sample_tables):
        sql = "ALTER TABLE trade_dwd.dwd_order_detail ADD COLUMN hack INT"
        errors = validate_sql(sql, sample_tables)
        assert len(errors) >= 1


class TestValidateSqlChecksTables:
    def test_unknown_table(self, sample_tables):
        sql = "SELECT * FROM trade_dwd.non_existent_table"
        errors = validate_sql(sql, sample_tables)
        assert len(errors) >= 1
        assert any("non_existent_table" in e for e in errors)

    def test_unknown_database_table(self, sample_tables):
        sql = "SELECT * FROM other_db.some_table"
        errors = validate_sql(sql, sample_tables)
        assert len(errors) >= 1
        assert any("some_table" in e for e in errors)


class TestValidateSqlChecksColumns:
    def test_unknown_column(self, sample_tables):
        sql = "SELECT non_existent_col FROM trade_dwd.dwd_order_detail"
        errors = validate_sql(sql, sample_tables)
        assert len(errors) >= 1
        assert any("non_existent_col" in e for e in errors)

    def test_unknown_column_with_valid_table(self, sample_tables):
        sql = (
            "SELECT user_id, fake_column "
            "FROM trade_dwd.dim_user "
            "WHERE province = '北京'"
        )
        errors = validate_sql(sql, sample_tables)
        assert len(errors) >= 1
        assert any("fake_column" in e for e in errors)


class TestValidateSqlRejectsSelectInto:
    def test_rejects_select_into(self, sample_tables):
        sql = "SELECT order_id, amount INTO new_table FROM trade_dwd.dwd_order_detail"
        errors = validate_sql(sql, sample_tables)
        assert len(errors) >= 1
        assert any("INTO" in e or "禁止" in e for e in errors)

    def test_rejects_select_into_with_where(self, sample_tables):
        sql = (
            "SELECT user_id, username INTO backup_users "
            "FROM trade_dwd.dim_user WHERE province = '北京'"
        )
        errors = validate_sql(sql, sample_tables)
        assert len(errors) >= 1


class TestValidateSqlRejectsCTEWithDML:
    def test_rejects_cte_with_delete(self, sample_tables):
        sql = (
            "WITH cte AS (DELETE FROM trade_dwd.dwd_order_detail RETURNING *) "
            "SELECT * FROM cte"
        )
        errors = validate_sql(sql, sample_tables)
        assert len(errors) >= 1
        assert any("禁止" in e or "CTE" in e for e in errors)

    def test_rejects_cte_with_insert(self, sample_tables):
        sql = (
            "WITH cte AS ("
            "  INSERT INTO trade_dwd.dwd_order_detail (order_id, user_id, amount, status, dt) "
            "  VALUES (99, 1, 100.0, 'A', '20260301') RETURNING *"
            ") SELECT * FROM cte"
        )
        errors = validate_sql(sql, sample_tables)
        assert len(errors) >= 1

    def test_valid_cte_passes(self, sample_tables):
        sql = (
            "WITH top_users AS ("
            "  SELECT user_id, SUM(amount) AS total "
            "  FROM trade_dwd.dwd_order_detail "
            "  WHERE dt = '20260301' "
            "  GROUP BY user_id"
            ") SELECT u.username, t.total "
            "FROM top_users t "
            "JOIN trade_dwd.dim_user u ON t.user_id = u.user_id"
        )
        errors = validate_sql(sql, sample_tables)
        assert errors == []


class TestValidateSqlSuccess:
    def test_simple_select(self, sample_tables):
        sql = (
            "SELECT order_id, amount, status "
            "FROM trade_dwd.dwd_order_detail "
            "WHERE dt = '20260301'"
        )
        errors = validate_sql(sql, sample_tables)
        assert errors == []

    def test_aggregation_query(self, sample_tables):
        sql = (
            "SELECT status, COUNT(*) AS cnt, SUM(amount) AS total "
            "FROM trade_dwd.dwd_order_detail "
            "WHERE dt = '20260301' "
            "GROUP BY status"
        )
        errors = validate_sql(sql, sample_tables)
        assert errors == []

    def test_join_query(self, sample_tables):
        sql = (
            "SELECT o.order_id, u.username, o.amount "
            "FROM trade_dwd.dwd_order_detail o "
            "JOIN trade_dwd.dim_user u ON o.user_id = u.user_id "
            "WHERE o.dt = '20260301'"
        )
        errors = validate_sql(sql, sample_tables)
        assert errors == []

    def test_star_select(self, sample_tables):
        sql = "SELECT * FROM trade_dwd.dim_product"
        errors = validate_sql(sql, sample_tables)
        assert errors == []

    def test_subquery(self, sample_tables):
        sql = (
            "SELECT user_id, total FROM ("
            "  SELECT user_id, SUM(amount) AS total "
            "  FROM trade_dwd.dwd_order_detail "
            "  WHERE dt = '20260301' "
            "  GROUP BY user_id"
            ") sub WHERE total > 100"
        )
        errors = validate_sql(sql, sample_tables)
        assert errors == []


class TestValidatePartitionPruning:
    def test_validate_sql_missing_where(self, sample_tables):
        """分区表查询缺少 WHERE 子句 → 拦截"""
        sql = "SELECT order_id, amount FROM trade_dwd.dwd_order_detail"
        errors = validate_sql(sql, sample_tables)
        assert len(errors) >= 1
        assert any("分区" in e and "dt" in e for e in errors)

    def test_validate_sql_missing_partition_key(self, sample_tables):
        """分区表有 WHERE 但不含分区键 → 拦截"""
        sql = (
            "SELECT order_id, amount "
            "FROM trade_dwd.dwd_order_detail "
            "WHERE status = 'paid'"
        )
        errors = validate_sql(sql, sample_tables)
        assert len(errors) >= 1
        assert any("分区" in e and "dt" in e for e in errors)

    def test_validate_sql_with_partition_key(self, sample_tables):
        """分区表 WHERE 中包含分区键 → 通过"""
        sql = (
            "SELECT order_id, amount "
            "FROM trade_dwd.dwd_order_detail "
            "WHERE dt = '20260410'"
        )
        errors = validate_sql(sql, sample_tables)
        assert errors == []

    def test_validate_sql_non_partitioned_table(self, sample_tables):
        """无分区表全表查询 → 通过"""
        sql = "SELECT user_id, username FROM trade_dwd.dim_user"
        errors = validate_sql(sql, sample_tables)
        assert errors == []

    def test_validate_sql_partition_key_with_alias(self, sample_tables):
        """分区表带别名，WHERE 中通过别名引用分区键 → 通过"""
        sql = (
            "SELECT o.order_id, o.amount "
            "FROM trade_dwd.dwd_order_detail o "
            "WHERE o.dt = '20260410'"
        )
        errors = validate_sql(sql, sample_tables)
        assert errors == []

    def test_validate_sql_join_partitioned_and_non_partitioned(self, sample_tables):
        """JOIN 分区表 + 无分区表，只要分区表有分区键过滤即可"""
        sql = (
            "SELECT o.order_id, u.username "
            "FROM trade_dwd.dwd_order_detail o "
            "JOIN trade_dwd.dim_user u ON o.user_id = u.user_id "
            "WHERE o.dt = '20260410'"
        )
        errors = validate_sql(sql, sample_tables)
        assert errors == []
