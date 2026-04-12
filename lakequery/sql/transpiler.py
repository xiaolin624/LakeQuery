import logging

import sqlglot

logger = logging.getLogger(__name__)


def transpile_sql(sql: str, target_dialect: str) -> str:
    try:
        results = sqlglot.transpile(sql, read=None, write=target_dialect)
        return results[0]
    except sqlglot.errors.ParseError as e:
        raise ValueError(f"SQL 转译失败: {e}") from e
