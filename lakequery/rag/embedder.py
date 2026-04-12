import functools
import logging

from sentence_transformers import SentenceTransformer

from lakequery.config import settings

logger = logging.getLogger(__name__)


@functools.lru_cache(maxsize=1)
def get_embedder() -> SentenceTransformer:
    logger.info("Loading embedding model: %s", settings.embedding_model)
    return SentenceTransformer(settings.embedding_model)
