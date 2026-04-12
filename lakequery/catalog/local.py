import json
import logging
from pathlib import Path

from lakequery.models.schema import TableMeta

logger = logging.getLogger(__name__)

_LOCAL_CATALOG_PATH = Path(__file__).parent / "local_tables.json"


def load_local_tables() -> list[TableMeta]:
    if not _LOCAL_CATALOG_PATH.exists():
        return []
    with open(_LOCAL_CATALOG_PATH, encoding="utf-8") as f:
        raw = json.load(f)
    return [TableMeta(**item) for item in raw]
