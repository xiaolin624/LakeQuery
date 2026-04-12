from unittest.mock import MagicMock, patch

import pytest

from lakequery.models.schema import TableMeta


class TestHMSClientFetchTables:
    """HMSClient.fetch_database_schema 解析 SHOW TABLES + DESCRIBE 结果"""

    def _mock_cursor(self):
        """构造模拟 Hive cursor，依次返回 SHOW TABLES 和 DESCRIBE 结果"""
        cursor = MagicMock()
        call_count = 0

        def execute_side_effect(sql):
            nonlocal call_count
            call_count += 1
            cursor._call_count = call_count

        def fetchall_side_effect():
            # 第 1 次调用：SHOW TABLES
            if cursor._call_count == 1:
                return [("dwd_order_detail",), ("dim_user",)]
            # 第 2 次：DESCRIBE dwd_order_detail
            if cursor._call_count == 2:
                return [
                    ("order_id", "bigint", "订单ID"),
                    ("user_id", "bigint", "用户ID"),
                    ("amount", "double", "订单金额"),
                    ("dt", "string", "日期分区"),
                    ("", None, None),
                    ("# Partition Information", None, None),
                    ("# col_name", "data_type", "comment"),
                    ("", None, None),
                    ("dt", "string", "日期分区"),
                ]
            # 第 3 次：DESCRIBE dim_user
            if cursor._call_count == 3:
                return [
                    ("user_id", "bigint", "用户ID"),
                    ("username", "string", "用户名"),
                    ("province", "string", "省份"),
                ]

        cursor.execute = MagicMock(side_effect=execute_side_effect)
        cursor.fetchall = MagicMock(side_effect=fetchall_side_effect)
        return cursor

    @patch("pyhive.hive.connect")
    def test_hms_fetch_tables(self, mock_connect):
        from lakequery.catalog.hms import HMSClient

        mock_conn = MagicMock()
        mock_conn.cursor.return_value = self._mock_cursor()
        mock_connect.return_value = mock_conn

        client = HMSClient(host="fake-hive", port=10000)
        tables = client.fetch_database_schema(database="trade_dwd")

        assert len(tables) == 2
        assert all(isinstance(t, TableMeta) for t in tables)

        # 验证第一张表
        order_table = [t for t in tables if t.table_name == "dwd_order_detail"][0]
        assert order_table.database == "trade_dwd"
        col_names = [c.name for c in order_table.columns]
        assert "order_id" in col_names
        assert "amount" in col_names
        assert "dt" in col_names
        assert order_table.partition_keys == ["dt"]
        dt_col = [c for c in order_table.columns if c.name == "dt"][0]
        assert dt_col.is_partition_key is True

        # 验证第二张表（无分区）
        user_table = [t for t in tables if t.table_name == "dim_user"][0]
        assert user_table.partition_keys == []
        assert len(user_table.columns) == 3

    @patch("pyhive.hive.connect")
    def test_hms_fetch_empty_database(self, mock_connect):
        from lakequery.catalog.hms import HMSClient

        mock_conn = MagicMock()
        cursor = MagicMock()
        cursor.fetchall.return_value = []
        mock_conn.cursor.return_value = cursor
        mock_connect.return_value = mock_conn

        client = HMSClient(host="fake-hive", port=10000)
        tables = client.fetch_database_schema(database="empty_db")
        assert tables == []

    @patch("pyhive.hive.connect")
    def test_hms_fetch_filters_blank_rows(self, mock_connect):
        """DESCRIBE 返回含空行、注释行时应正确过滤"""
        from lakequery.catalog.hms import HMSClient

        mock_conn = MagicMock()
        cursor = MagicMock()
        call_count = 0

        def execute_side_effect(sql):
            nonlocal call_count
            call_count += 1
            cursor._call_count = call_count

        cursor.execute = MagicMock(side_effect=execute_side_effect)
        cursor.fetchall = MagicMock(side_effect=[
            [("test_table",)],  # SHOW TABLES
            [
                ("id", "int", "主键"),
                ("", None, None),
                ("# Detailed Table Information", None, None),
                ("Database:", "mydb", None),
                ("Owner:", "hive", None),
                ("# col_name", "data_type", "comment"),
            ],  # DESCRIBE FORMATTED test_table
        ])
        mock_conn.cursor.return_value = cursor
        mock_connect.return_value = mock_conn

        client = HMSClient(host="fake-hive", port=10000)
        tables = client.fetch_database_schema(database="mydb")

        assert len(tables) == 1
        assert len(tables[0].columns) == 1
        assert tables[0].columns[0].name == "id"
