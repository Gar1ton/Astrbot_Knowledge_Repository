from pathlib import Path

from core.config import EmbeddingConfig
from core.index_compatibility import IndexCompatibilityStore, embedding_fingerprint


def test_embedding_fingerprint_changes_with_runtime_dimension() -> None:
    config = EmbeddingConfig(provider="external", model="model", base_url="https://example.test")

    assert embedding_fingerprint(config, 7) != embedding_fingerprint(config, 8)


def test_index_compatibility_invalidates_and_recovers_after_rebuild(tmp_path: Path) -> None:
    path = tmp_path / "compat.json"
    store = IndexCompatibilityStore(path)

    store.mark_milvus_compatible("fp-old")
    store.mark_lightrag_compatible("papers", "fp-old")
    store.mark_milvus_incompatible("schema mismatch")

    assert not store.is_milvus_compatible("fp-old")
    assert store.is_lightrag_compatible("papers", "fp-old")
    assert store.reason("milvus") == "schema mismatch"

    store.mark_all_incompatible("embedding changed")

    assert not store.is_milvus_compatible("fp-old")
    assert not store.is_lightrag_compatible("papers", "fp-old")
    assert store.reason("milvus") == "embedding changed"

    store.mark_milvus_compatible("fp-new")
    store.mark_lightrag_compatible("papers", "fp-new")
    reloaded = IndexCompatibilityStore(path)
    assert reloaded.is_milvus_compatible("fp-new")
    assert reloaded.is_lightrag_compatible("papers", "fp-new")
