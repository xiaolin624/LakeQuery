import contextlib
from collections.abc import Generator

import duckdb
import sqlglot
from sqlglot import exp

from lakequery.models.schema import TableMeta

TYPE_MAP: dict[str, str] = {
    "STRING": "VARCHAR",
    "INT": "INTEGER",
    "BIGINT": "BIGINT",
    "DOUBLE": "DOUBLE",
    "FLOAT": "FLOAT",
    "BOOLEAN": "BOOLEAN",
    "TIMESTAMP": "TIMESTAMP",
    "DATE": "DATE",
    "DECIMAL": "DECIMAL",
    "TINYINT": "TINYINT",
    "SMALLINT": "SMALLINT",
    "BINARY": "BLOB",
}


def _safe_id(name: str) -> str:
    return exp.to_identifier(name, quoted=True).sql("duckdb")


def sync_virtual_tables(
    conn: duckdb.DuckDBPyConnection, tables: list[TableMeta]
) -> None:
    for table in tables:
        db_id = _safe_id(table.database)
        table_id = f"{db_id}.{_safe_id(table.table_name)}"
        conn.execute(f"CREATE SCHEMA IF NOT EXISTS {db_id}")
        col_defs = ", ".join(
            f"{_safe_id(c.name)} {TYPE_MAP.get(c.data_type.upper(), 'VARCHAR')}"
            for c in table.columns
        )
        conn.execute(f"CREATE OR REPLACE TABLE {table_id} ({col_defs})")


def duckdb_dry_run(conn: duckdb.DuckDBPyConnection, sql: str) -> list[str]:
    errors: list[str] = []
    try:
        conn.execute(f"EXPLAIN {sql}")
    except duckdb.Error as e:
        msg = str(e).split("\n")[0][:200]
        errors.append(f"DuckDB dry-run 失败: {msg}")
    return errors


@contextlib.contextmanager
def SandboxManager(tables: list[TableMeta]) -> Generator[duckdb.DuckDBPyConnection, None, None]:
    conn = duckdb.connect(":memory:")
    try:
        conn.execute("SET enable_external_access = false")
        conn.execute("SET enable_object_cache = false")
        sync_virtual_tables(conn, tables)
        yield conn
    finally:
        conn.close()
