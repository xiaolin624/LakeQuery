from unittest.mock import MagicMock, patch

import pytest
from pyiceberg.partitioning import PartitionField, PartitionSpec
from pyiceberg.schema import Schema
from pyiceberg.transforms import IdentityTransform
from pyiceberg.types import (
    FloatType,
    IntegerType,
    ListType,
    MapType,
    NestedField,
    StringType,
    StructType,
    TimestampType,
)

from lakequery.catalog.iceberg_rest import IcebergClient
from lakequery.models.schema import TableMeta


def _make_mock_catalog(tables_by_ns: dict[str, list[tuple[str, Schema, PartitionSpec]]]):
    catalog = MagicMock()
    catalog.list_namespaces.return_value = [
        (ns,) for ns in tables_by_ns
    ]

    def list_tables(ns):
        return [(ns, tbl[0]) for tbl in tables_by_ns.get(ns, [])]

    catalog.list_tables.side_effect = list_tables

    table_map: dict[str, MagicMock] = {}
    for ns, tbl_list in tables_by_ns.items():
        for tbl_name, schema, spec in tbl_list:
            mock_table = MagicMock()
            mock_table.schema.return_value = schema
            mock_table.spec.return_value = spec
            mock_table.location.return_value = f"s3://warehouse/{ns}/{tbl_name}"
            mock_table.metadata = MagicMock()
            mock_table.metadata.format_version = 2
            table_map[f"{ns}.{tbl_name}"] = mock_table

    def load_table(identifier):
        if isinstance(identifier, tuple):
            key = ".".join(identifier)
        else:
            key = str(identifier)
        return table_map[key]

    catalog.load_table.side_effect = load_table
    return catalog


class TestIcebergFetchTables:
    @pytest.fixture
    def order_schema(self):
        return Schema(
            NestedField(1, "order_id", IntegerType(), required=True),
            NestedField(2, "user_id", IntegerType()),
            NestedField(3, "amount", FloatType()),
            NestedField(4, "created_at", TimestampType()),
            NestedField(5, "dt", StringType()),
        )

    @pytest.fixture
    def order_partition_spec(self):
        return PartitionSpec(
            PartitionField(source_id=5, field_id=1000, transform=IdentityTransform(), name="dt"),
        )

    @pytest.fixture
    def complex_schema(self):
        """包含嵌套类型的 Schema"""
        return Schema(
            NestedField(1, "id", IntegerType(), required=True),
            NestedField(2, "tags", ListType(3, StringType())),
            NestedField(4, "props", MapType(5, StringType(), 6, IntegerType())),
            NestedField(7, "address", StructType(
                NestedField(8, "city", StringType()),
                NestedField(9, "zip", StringType()),
            )),
        )

    def test_iceberg_fetch_tables(self, order_schema, order_partition_spec):
        mock_catalog = _make_mock_catalog({
            "trade_dwd": [("dwd_order_detail", order_schema, order_partition_spec)],
        })

        with patch("lakequery.catalog.iceberg_rest.load_catalog", return_value=mock_catalog):
            client = IcebergClient(catalog_name="test", rest_uri="http://fake:8181")
            tables = client.fetch_database_schema("trade_dwd")

        assert len(tables) == 1
        t = tables[0]
        assert isinstance(t, TableMeta)
        assert t.database == "trade_dwd"
        assert t.table_name == "dwd_order_detail"
        assert t.partition_keys == ["dt"]

        col_names = [c.name for c in t.columns]
        assert "order_id" in col_names
        assert "dt" in col_names

        dt_col = next(c for c in t.columns if c.name == "dt")
        assert dt_col.is_partition_key is True

        col_types = {c.name: c.data_type for c in t.columns}
        assert col_types["order_id"] == "INT"
        assert col_types["amount"] == "FLOAT"

    def test_iceberg_fetch_tables_complex_types(self, complex_schema):
        empty_spec = PartitionSpec()
        mock_catalog = _make_mock_catalog({
            "analytics": [("events", complex_schema, empty_spec)],
        })

        with patch("lakequery.catalog.iceberg_rest.load_catalog", return_value=mock_catalog):
            client = IcebergClient(catalog_name="test", rest_uri="http://fake:8181")
            tables = client.fetch_database_schema("analytics")

        assert len(tables) == 1
        t = tables[0]
        assert t.partition_keys == []

        col_types = {c.name: c.data_type for c in t.columns}
        assert col_types["tags"] == "LIST"
        assert col_types["props"] == "MAP"
        assert col_types["address"] == "STRUCT"

    def test_iceberg_fetch_tables_empty_namespace(self):
        mock_catalog = _make_mock_catalog({"empty_ns": []})

        with patch("lakequery.catalog.iceberg_rest.load_catalog", return_value=mock_catalog):
            client = IcebergClient(catalog_name="test", rest_uri="http://fake:8181")
            tables = client.fetch_database_schema("empty_ns")

        assert tables == []

    def test_iceberg_fetch_tables_multi_partition(self, order_schema):
        """多分区键场景"""
        multi_spec = PartitionSpec(
            PartitionField(source_id=5, field_id=1000, transform=IdentityTransform(), name="dt"),
            PartitionField(source_id=2, field_id=1001, transform=IdentityTransform(), name="user_id"),
        )
        mock_catalog = _make_mock_catalog({
            "db": [("tbl", order_schema, multi_spec)],
        })

        with patch("lakequery.catalog.iceberg_rest.load_catalog", return_value=mock_catalog):
            client = IcebergClient(catalog_name="test", rest_uri="http://fake:8181")
            tables = client.fetch_database_schema("db")

        assert set(tables[0].partition_keys) == {"dt", "user_id"}
