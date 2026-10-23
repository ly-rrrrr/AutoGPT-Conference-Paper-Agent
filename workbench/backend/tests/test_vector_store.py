from app.config import Settings
from app.vector_store import collection_name, milvus_ready


class FakeMilvusClient:
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.closed = False

    def list_collections(self, **kwargs):
        return []

    def close(self):
        self.closed = True


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
