from app.config import Settings
from app.vector_store import VectorStore, collection_name, milvus_ready


class FakeMilvusClient:
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.closed = False

    def list_collections(self, **kwargs):
        return []

    def close(self):
        self.closed = True

    def has_collection(self, collection_name, **kwargs):
        return False

    def create_collection(self, collection_name, **kwargs):
        self.created = (collection_name, kwargs)

    def upsert(self, collection_name, data, **kwargs):
        self.upserted = (collection_name, data, kwargs)
        return {"upsert_count": len(data)}

    def search(self, collection_name, **kwargs):
        self.searched = (collection_name, kwargs)
        return [[{"id": "chunk-1", "distance": 0.95}]]


def test_collection_name_encodes_asset_and_embedding_model():
    settings = Settings(milvus_collection_prefix="workbench")

    name = collection_name("paper chunk", "text-embedding-3-small", settings)

    assert name == "workbench_paper_chunk_text_embedding_3_small"


def test_milvus_health_uses_configured_connection():
    clients = []

    def factory(**kwargs):
        client = FakeMilvusClient(**kwargs)
        clients.append(client)
        return client

    settings = Settings(
        milvus_uri="http://milvus.example:19530",
        milvus_token="secret-token",
        milvus_database="research",
        milvus_timeout_seconds=3,
    )

    assert milvus_ready(settings, client_factory=factory) is True
    assert clients[0].kwargs == {
        "uri": "http://milvus.example:19530",
        "db_name": "research",
        "timeout": 3,
        "token": "secret-token",
    }
    assert clients[0].closed is True


def test_milvus_health_returns_false_on_connection_failure():
    def factory(**kwargs):
        raise RuntimeError("offline")

    assert milvus_ready(Settings(), client_factory=factory) is False


def test_vector_store_creates_model_scoped_collection_and_upserts():
    clients = []

    def factory(**kwargs):
        client = FakeMilvusClient(**kwargs)
        clients.append(client)
        return client

    store = VectorStore(Settings(milvus_collection_prefix="workbench"), factory)
    name = store.ensure_collection("paragraph", "embedding-v1", 3)
    result = store.upsert(
        name,
        entity_id="chunk-1",
        vector=[0.1, 0.2, 0.3],
        paper_id="paper-1",
        chunk_id="chunk-1",
        content_sha256="hash",
        kind="paragraph",
    )

    assert name == "workbench_paragraph_embedding_v1"
    assert clients[0].created[1]["dimension"] == 3
    assert result == {"upsert_count": 1}
