import logging

from pyiceberg.catalog import load_catalog
from pyiceberg.types import ListType, MapType, StructType

from lakequery.models.schema import ColumnMeta, TableMeta

logger = logging.getLogger(__name__)


def _map_iceberg_type(field_type) -> str:
    if isinstance(field_type, StructType):
        return "STRUCT"
    if isinstance(field_type, ListType):
        return "LIST"
    if isinstance(field_type, MapType):
        return "MAP"
    return str(field_type).upper()


class IcebergClient:
    def __init__(self, catalog_name: str, rest_uri: str):
        self.catalog = load_catalog(catalog_name, type="rest", uri=rest_uri)

    def fetch_database_schema(self, namespace: str) -> list[TableMeta]:
        table_ids = self.catalog.list_tables(namespace)
        tables: list[TableMeta] = []

        for ns, table_name in table_ids:
            try:
                table = self.catalog.load_table((ns, table_name))
                schema = table.schema()
                spec = table.spec()

                partition_keys = [
                    schema.find_field(pf.source_id).name
                    for pf in spec.fields
                ]

                columns = []
                for field in schema.fields:
                    columns.append(ColumnMeta(
                        name=field.name,
                        data_type=_map_iceberg_type(field.field_type),
                        is_partition_key=(field.name in partition_keys),
                    ))

                tables.append(TableMeta(
                    catalog="iceberg",
                    database=namespace,
                    table_name=table_name,
                    columns=columns,
                    partition_keys=partition_keys,
                ))
            except Exception:
                logger.exception("Failed to load Iceberg table %s.%s", ns, table_name)

        return tables
