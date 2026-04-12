from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    model_config = {"env_prefix": "LQ_", "env_file": ".env", "env_file_encoding": "utf-8"}

    # LLM
    llm_api_key: str = ""
    llm_base_url: str = "https://ark.cn-beijing.volces.com/api/v3"
    llm_model: str = "ep-m-20251204150216-qnc57"
    llm_temperature: float = 0.0
    llm_max_tokens: int = 4096

    # Qdrant
    qdrant_url: str = "http://localhost:6333"
    qdrant_collection: str = "table_schemas"
    qdrant_golden_collection: str = "golden_queries"
    qdrant_api_key: str = ""

    # Golden Query
    golden_query_threshold: float = 0.95

    # Embedding
    embedding_model: str = "BAAI/bge-large-zh-v1.5"
    embedding_dim: int = 1024

    # DuckDB
    duckdb_path: str = ":memory:"

    # Agent
    max_retries: int = 3
    target_dialect: str = "hive"

    # Server
    host: str = "0.0.0.0"
    port: int = 8000

    # HMS
    hms_host: str = ""
    hms_port: int = 10000

    # Langfuse
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_host: str = ""


settings = Settings()
