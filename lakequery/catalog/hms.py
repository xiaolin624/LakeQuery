import logging

from pyhive import hive

from lakequery.models.schema import ColumnMeta, TableMeta

logger = logging.getLogger(__name__)


class HMSClient:
    def __init__(self, host: str, port: int = 10000, auth: str = "NONE", username: str = "hive"):
        self.host = host
        self.port = port
        self.auth = auth
        self.username = username

    def fetch_database_schema(self, database: str) -> list[TableMeta]:
        logger.info("Connecting to HiveServer2 at %s:%s (auth=%s, user=%s, db=%s)", self.host, self.port, self.auth, self.username, database)
        conn = hive.connect(host=self.host, port=self.port, database=database, auth=self.auth, username=self.username)
        try:
            cursor = conn.cursor()
            cursor.execute("SHOW TABLES")
            table_names = [row[0] for row in cursor.fetchall()]

            tables = []
            for table_name in table_names:
                cursor.execute(f"DESCRIBE {table_name}")
                rows = cursor.fetchall()
                columns, partition_keys = self._parse_describe(rows)
                tables.append(TableMeta(
                    catalog="default",
                    database=database,
                    table_name=table_name,
                    columns=columns,
                    partition_keys=partition_keys,
                ))
            return tables
        finally:
            conn.close()

    @staticmethod
    def _parse_describe(rows: list[tuple]) -> tuple[list[ColumnMeta], list[str]]:
        columns: list[ColumnMeta] = []
        partition_keys: list[str] = []
        in_partition_section = False

        for row in rows:
            col_name = (row[0] or "").strip()
            col_type = (row[1] or "").strip() if row[1] else ""
            col_comment = (row[2] or "").strip() if len(row) > 2 and row[2] else ""

            if not col_name or col_name.startswith("#"):
                if col_name == "# Partition Information":
                    in_partition_section = True
                continue

            if ":" in col_name:
                continue

            if in_partition_section:
                partition_keys.append(col_name)
            else:
                columns.append(ColumnMeta(
                    name=col_name,
                    data_type=col_type,
                    comment=col_comment,
                ))

        for col in columns:
            if col.name in partition_keys:
                col.is_partition_key = True

        return columns, partition_keys
