from pydantic import BaseModel


class QueryRequest(BaseModel):
    question: str
    dialect: str = "hive"
    catalog: str = "default"
    database: str = ""
    execute: bool = False


class QueryResponse(BaseModel):
    sql: str
    dialect: str
    tables_used: list[str]
    validation_passed: bool
    retry_count: int
    execution_result: list[dict] | None = None
    error: str | None = None
    answer: str | None = None


class HealthResponse(BaseModel):
    status: str
    catalogs_connected: list[str]
    vector_store_count: int


class CatalogSyncRequest(BaseModel):
    database: str
    catalog_type: str = "hms"
    hms_host: str = ""
    hms_port: int = 10000
    hms_auth: str = "NONE"
    hms_username: str = "hive"
    iceberg_rest_uri: str = ""


class ColumnMetaResponse(BaseModel):
    name: str
    data_type: str
    is_partition_key: bool = False
    comment: str = ""


class TableMetaResponse(BaseModel):
    table_name: str
    database: str
    columns: list[ColumnMetaResponse]


class CatalogSyncResponse(BaseModel):
    tables_synced: int
    vectors_indexed: int
    table_names: list[str]
    tables: list[TableMetaResponse] = []


class ParsedIntent(BaseModel):
    time_range: str | None = None
    dimensions: list[str] = []
    metrics: list[str] = []
    filters: list[str] = []
    sort: str | None = None
    ambiguous: bool = False
    clarification_question: str = ""
    is_metadata_query: bool = False


class GeneratedSQL(BaseModel):
    sql: str
    reasoning: str
    tables_used: list[str]
    partition_filters: list[str] = []


class GoldenQueryRequest(BaseModel):
    question: str
    sql: str


class GoldenQueryResponse(BaseModel):
    status: str
