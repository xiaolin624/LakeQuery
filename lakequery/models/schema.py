from pydantic import BaseModel


class ColumnMeta(BaseModel):
    name: str
    data_type: str
    comment: str = ""
    is_partition_key: bool = False


class TableMeta(BaseModel):
    catalog: str
    database: str
    table_name: str
    columns: list[ColumnMeta]
    partition_keys: list[str] = []
    comment: str = ""
    storage_format: str = ""
    location: str = ""

    @property
    def full_name(self) -> str:
        return f"{self.database}.{self.table_name}"

    def to_schema_text(self) -> str:
        cols = ", ".join(
            f"{c.name} {c.data_type}" + (f" -- {c.comment}" if c.comment else "")
            for c in self.columns
        )
        return f"{self.full_name}({cols}) [分区键: {','.join(self.partition_keys)}]"
