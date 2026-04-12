import logging

import sqlglot
from sqlglot import exp

from lakequery.models.schema import TableMeta

logger = logging.getLogger(__name__)

_FORBIDDEN_TYPES = (
    exp.Insert,
    exp.Update,
    exp.Delete,
    exp.Drop,
    exp.Create,
    exp.Alter,
)


def _validate_partition_keys(
    tree: exp.Expression,
    candidate_tables: list[TableMeta],
    alias_to_table: dict[str, str],
) -> list[str]:
    errors: list[str] = []

    # 构建 分区表名 → 分区键集 的映射
    partitioned: dict[str, list[str]] = {}
    for t in candidate_tables:
        if t.partition_keys:
            partitioned[t.full_name.lower()] = t.partition_keys
            partitioned[t.table_name.lower()] = t.partition_keys

    if not partitioned:
        return errors

    # 找出查询中引用的分区表（去重）
    referenced_partitioned: dict[str, list[str]] = {}
    for tbl in tree.find_all(exp.Table):
        table_name = tbl.name
        db = tbl.db
        full = f"{db}.{table_name}".lower() if db else table_name.lower()
        if full in partitioned:
            referenced_partitioned[full] = partitioned[full]

    if not referenced_partitioned:
        return errors

    # 收集所有 WHERE 子句中出现的列名（含子查询 / CTE）
    where_columns: set[str] = set()
    for where_node in tree.find_all(exp.Where):
        for col_node in where_node.find_all(exp.Column):
            where_columns.add(col_node.name.lower())

    # 逐个检查分区表的分区键是否出现在 WHERE 中
    checked: set[str] = set()
    for table_ref, keys in referenced_partitioned.items():
        if table_ref in checked:
            continue
        checked.add(table_ref)
        for key in keys:
            if key.lower() not in where_columns:
                errors.append(
                    f"表 {table_ref} 是分区表，必须在 WHERE 子句中包含分区键 {keys} 的过滤条件，以防止全表扫描"
                )
                break

    return errors


def validate_sql(sql: str, candidate_tables: list[TableMeta]) -> list[str]:
    errors: list[str] = []

    # 1. 解析 AST
    try:
        tree = sqlglot.parse_one(sql)
    except sqlglot.errors.ParseError as e:
        errors.append(f"SQL 语法解析失败: {e}")
        return errors

    # 2. 检查语句类型 —— 只允许 SELECT 及其变体
    if isinstance(tree, _FORBIDDEN_TYPES):
        stmt_type = type(tree).__name__
        errors.append(f"禁止执行 {stmt_type} 语句，只允许 SELECT 查询")
        return errors

    if not isinstance(tree, (exp.Select, exp.Union, exp.Intersect, exp.Except, exp.Subquery)):
        stmt_type = type(tree).__name__
        errors.append(f"不允许的语句类型 {stmt_type}，只允许 SELECT 查询")
        return errors

    # 2a. 检查 SELECT ... INTO（数据导出）
    if tree.find(exp.Into):
        errors.append("禁止使用 SELECT ... INTO 语句")
        return errors

    # 2b. 检查 CTE body 中是否包含非 SELECT 语句
    cte_aliases: set[str] = set()
    for with_node in tree.find_all(exp.With):
        for cte_expr in with_node.expressions:
            if hasattr(cte_expr, "alias") and cte_expr.alias:
                cte_aliases.add(cte_expr.alias.lower())
            cte_body = cte_expr.this
            if isinstance(cte_body, _FORBIDDEN_TYPES):
                stmt_type = type(cte_body).__name__
                errors.append(f"CTE 中禁止执行 {stmt_type} 语句，只允许 SELECT 查询")
    if errors:
        return errors

    # 3. 构建已知表和列的索引
    known_tables: dict[str, set[str]] = {}
    for t in candidate_tables:
        # 同时用 full_name 和 table_name 作为 key，方便匹配
        col_names = {c.name for c in t.columns}
        known_tables[t.full_name.lower()] = col_names
        known_tables[t.table_name.lower()] = col_names

    # 4. 提取 SQL 中引用的表，建立别名映射
    alias_to_table: dict[str, str] = {}
    referenced_tables: list[str] = []

    for tbl in tree.find_all(exp.Table):
        table_name = tbl.name
        db = tbl.db
        full = f"{db}.{table_name}".lower() if db else table_name.lower()

        # CTE 别名不做表名校验
        if full in cte_aliases:
            alias = tbl.alias
            if alias:
                alias_to_table[alias.lower()] = "__cte__"
            else:
                alias_to_table[table_name.lower()] = "__cte__"
            continue

        referenced_tables.append(full)

        # 记录别名映射
        alias = tbl.alias
        if alias:
            alias_to_table[alias.lower()] = full
        else:
            alias_to_table[table_name.lower()] = full

    # 5. 校验表名
    for ref in referenced_tables:
        if ref not in known_tables:
            errors.append(f"未知的表: {ref}")

    if errors:
        return errors

    # 6. 收集 SQL 中定义的表达式别名（子查询列别名、SELECT AS 别名等）
    defined_aliases: set[str] = set()
    for alias_node in tree.find_all(exp.Alias):
        defined_aliases.add(alias_node.alias.lower())
    # 子查询别名也加入（防止被当作表名校验）
    for subq in tree.find_all(exp.Subquery):
        if subq.alias:
            alias_to_table[subq.alias.lower()] = "__subquery__"

    # 7. 校验列名
    all_columns: set[str] = set()
    for ref in referenced_tables:
        cols = known_tables.get(ref, set())
        all_columns.update(cols)

    for col_node in tree.find_all(exp.Column):
        col_name = col_node.name
        # 跳过 * (star)
        if col_name == "*":
            continue
        # 跳过 SQL 中定义的别名引用
        if col_name.lower() in defined_aliases:
            continue

        # 如果列有表限定符，只在该表的列集中查找
        table_ref = col_node.table
        if table_ref:
            resolved = alias_to_table.get(table_ref.lower(), table_ref.lower())
            # 子查询别名表不校验列
            if resolved == "__subquery__":
                continue
            table_cols = known_tables.get(resolved, set())
            if table_cols and col_name not in table_cols:
                errors.append(f"表 {resolved} 中未找到列: {col_name}")
        else:
            # 无表限定符，在所有候选表列中查找
            if col_name not in all_columns:
                errors.append(f"未知的列: {col_name}")

    # 8. 分区键校验
    errors.extend(_validate_partition_keys(tree, candidate_tables, alias_to_table))

    return errors
