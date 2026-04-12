import hashlib
import uuid

from qdrant_client import AsyncQdrantClient
from qdrant_client.models import PointStruct

from lakequery.config import settings
from lakequery.models.schema import TableMeta


def _table_id(table: TableMeta) -> str:
    return hashlib.md5(table.full_name.encode()).hexdigest()


async def index_tables(
    client: AsyncQdrantClient,
    embedder,
    tables: list[TableMeta],
) -> None:
    points = []
    for table in tables:
        text = table.to_schema_text()
        vector = embedder.encode(text)
        if hasattr(vector, "tolist"):
            vector = vector.tolist()
        point = PointStruct(
            id=_table_id(table),
            vector=vector,
            payload={
                "full_name": table.full_name,
                "database": table.database,
                "table_name": table.table_name,
                "schema_text": text,
                "table_meta": table.model_dump(),
            },
        )
        points.append(point)

    await client.upsert(
        collection_name=settings.qdrant_collection,
        points=points,
    )


async def save_golden_query(
    client: AsyncQdrantClient,
    embedder,
    question: str,
    sql: str,
) -> None:
    vector = embedder.encode(question)
    if hasattr(vector, "tolist"):
        vector = vector.tolist()

    point = PointStruct(
        id=uuid.uuid4().hex,
        vector=vector,
        payload={"question": question, "sql": sql},
    )

    await client.upsert(
        collection_name=settings.qdrant_golden_collection,
        points=[point],
    )
