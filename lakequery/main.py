import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from qdrant_client.models import Distance, VectorParams

from lakequery.api.routes import router
from lakequery.config import settings

logger = logging.getLogger(__name__)


async def ensure_collections() -> None:
    from lakequery.agent.nodes import get_qdrant_client

    client = get_qdrant_client()
    for name in [settings.qdrant_collection, settings.qdrant_golden_collection]:
        try:
            exists = await client.collection_exists(name)
            if not exists:
                await client.create_collection(
                    collection_name=name,
                    vectors_config=VectorParams(
                        size=settings.embedding_dim,
                        distance=Distance.COSINE,
                    ),
                )
                logger.info("Created Qdrant collection: %s", name)
        except Exception as e:
            logger.warning("无法初始化 Qdrant collection %s: %s", name, e)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    await ensure_collections()
    yield


app = FastAPI(title="LakeQuery", version="0.1.0", lifespan=lifespan)
app.include_router(router)
