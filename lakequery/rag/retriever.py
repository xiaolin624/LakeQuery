from qdrant_client import AsyncQdrantClient
from qdrant_client.models import FieldCondition, Filter, MatchValue

from lakequery.config import settings
from lakequery.models.schema import TableMeta


async def search_tables(
    client: AsyncQdrantClient,
    embedder,
    query: str,
    database_hint: str | None = None,
    top_k: int = 5,
) -> list[TableMeta]:
    query_vector = embedder.encode(query)
    if hasattr(query_vector, "tolist"):
        query_vector = query_vector.tolist()

    query_filter = None
    if database_hint:
        query_filter = Filter(
            must=[
                FieldCondition(
                    key="database",
                    match=MatchValue(value=database_hint),
                )
            ]
        )

    results = await client.query_points(
        collection_name=settings.qdrant_collection,
        query=query_vector,
        query_filter=query_filter,
        limit=top_k,
    )

    return [TableMeta(**r.payload["table_meta"]) for r in results.points]


async def search_golden_query(
    client: AsyncQdrantClient,
    embedder,
    question: str,
    threshold: float = 0.85,
) -> str | None:
    query_vector = embedder.encode(question)
    if hasattr(query_vector, "tolist"):
        query_vector = query_vector.tolist()

    results = await client.query_points(
        collection_name=settings.qdrant_golden_collection,
        query=query_vector,
        limit=1,
        with_payload=True,
        score_threshold=threshold,
    )

    if results.points:
        return results.points[0].payload["sql"]
    return None
