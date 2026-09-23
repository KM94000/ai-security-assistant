"""Fixtures partagees par les tests d'integration qui passent par l'API.

Les deux fixtures ci-dessous font pointer l'application sur une collection
jetable, puis y ingerent le corpus de reference. Sans cela, chaque test
dependrait de l'etat laisse par le precedent — le genre de couplage qui rend
une suite verte un jour et rouge le lendemain.

Elles vivent ici plutot que dans un module de test parce que deux fichiers s'en
servent desormais : `/query` (ticket 13) et `/agent` (ticket 21).
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from pathlib import Path

import anyio
import pytest
from qdrant_client import AsyncQdrantClient

from aisecassist.config import settings
from aisecassist.embeddings.sentence_transformer import SentenceTransformerEmbedder
from aisecassist.ingestion.pipeline import IngestionPipeline
from aisecassist.vectorstore.qdrant import QdrantVectorStore

_CORPUS = Path(__file__).resolve().parents[2] / "data" / "corpus"


@pytest.fixture
def collection_isolee(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    """Fait pointer l'application sur une collection jetable.

    Sans cela, le test dependrait de l'etat de la collection de travail — donc
    de ce qui a ete ingere avant lui, ce qui est exactement le genre de couplage
    qui rend un test vert un jour et rouge le lendemain.
    """
    nom = f"test_api_{uuid.uuid4().hex[:8]}"
    monkeypatch.setattr(settings, "qdrant_collection", nom)
    yield nom

    async def _supprimer() -> None:
        client = AsyncQdrantClient(url=settings.qdrant_url)
        try:
            if await client.collection_exists(nom):
                await client.delete_collection(nom)
        finally:
            await client.close()

    anyio.run(_supprimer)


@pytest.fixture
def corpus_indexe(collection_isolee: str) -> Iterator[str]:
    """Ingere le corpus de reference dans la collection jetable."""

    async def _ingerer() -> None:
        embedder = SentenceTransformerEmbedder(
            settings.embedding_model,
            settings.embedding_dimension,
            revision=settings.embedding_model_revision,
        )
        async with QdrantVectorStore(
            settings.qdrant_url, collection_isolee, embedding_model=settings.embedding_model_id
        ) as store:
            pipeline = IngestionPipeline(
                embedder,
                store,
                chunk_size=settings.chunk_size,
                chunk_overlap=settings.chunk_overlap,
                max_document_bytes=settings.max_document_bytes,
            )
            rapport = await pipeline.ingest_directory(_CORPUS)
            assert rapport.chunks_indexed > 0

    anyio.run(_ingerer)
    yield collection_isolee
