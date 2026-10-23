from unittest.mock import Mock, patch

from sqlalchemy import func, select

from app.asset_registry import ingest_tei_chunks, record_asset_revision
from app.embedding_indexer import index_document_chunks, pending_chunks, request_embeddings
from app.models import DocumentAsset, EmbeddingProviderConfig, VectorIndexRecord


class FakeVectorStore:
    def __init__(self):
        self.items = []

    def ensure_collection(self, asset_type, model, dimension):
        assert (asset_type, model, dimension) == ("document_chunk", "embed-v1", 3)
        return "workbench_document_chunk_embed_v1_d3"

    def upsert_many(self, collection, items):
        self.items.extend(items)
        return {"upsert_count": len(items)}

    def close(self):
        pass


def test_embedding_request_sends_configured_dimensions():
    config = EmbeddingProviderConfig(
        name="Embedding",
        provider="Compatible",
        base_url="https://example.com/v1",
        model_name="text-embedding-3-large",
        dimension=1024,
        secret_ref="embedding:test",
        is_default=True,
        status="ACTIVE",
    )
    response = Mock()
    response.raise_for_status.return_value = None
    response.json.return_value = {
        "data": [{"index": 0, "embedding": [0.1] * 1024}]
    }
    with patch("app.embedding_indexer.httpx.post", return_value=response) as post:
        vectors = request_embeddings(config, "secret", ["method paragraph"])

    assert len(vectors[0]) == 1024
    assert post.call_args.kwargs["json"]["dimensions"] == 1024


def test_incremental_index_skips_unchanged_chunks(
    api_session, seeded_db, tmp_path
):
    tei = """<TEI xmlns="http://www.tei-c.org/ns/1.0"><text><body><div><head>Method</head><p>First method paragraph.</p><p>Second method paragraph.</p></div></body></text></TEI>"""
    path = tmp_path / "paper.tei.xml"
    path.write_text(tei, encoding="utf-8")
    asset = DocumentAsset(
        paper_id=seeded_db["matched"].id,
        kind="grobid_tei",
        status="PARSED",
    )
    config = EmbeddingProviderConfig(
        name="Embedding",
        provider="Compatible",
        base_url="https://example.com/v1",
        model_name="embed-v1",
        dimension=3,
        secret_ref="embedding:test",
        is_default=True,
        status="ACTIVE",
    )
    api_session.add_all([asset, config])
    api_session.flush()
    revision = record_asset_revision(api_session, asset, path)
    ingest_tei_chunks(api_session, seeded_db["matched"].id, revision, tei)

    store = FakeVectorStore()
    with (
        patch("app.embedding_indexer.get_secret", return_value="secret"),
        patch(
            "app.embedding_indexer.request_embeddings",
            side_effect=lambda config, key, texts: [[0.1, 0.2, 0.3] for _ in texts],
        ),
    ):
        first = index_document_chunks(
            api_session,
            config.id,
            vector_store_factory=lambda: store,
        )
        second = pending_chunks(api_session, config, limit=100)

    assert first["indexed"] == 2
    assert len(store.items) == 2
    assert second == []
    assert api_session.scalar(select(func.count(VectorIndexRecord.id))) == 2
