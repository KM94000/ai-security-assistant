"""Test d'integration : ingestion du vrai corpus dans le vrai Qdrant.

Deselectionne par defaut. Exige le conteneur demarre et telecharge MiniLM :

    docker compose -f docker/docker-compose.yml up -d qdrant
    pytest -m integration

Collection jetable, supprimee ensuite.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from qdrant_client import AsyncQdrantClient

from aisecassist.config import settings
from aisecassist.embeddings.sentence_transformer import SentenceTransformerEmbedder
from aisecassist.ingestion.pipeline import IngestionPipeline
from aisecassist.vectorstore.qdrant import QdrantVectorStore

pytestmark = [pytest.mark.anyio, pytest.mark.integration]

_CORPUS = Path(__file__).resolve().parents[2] / "data" / "corpus"


@pytest.fixture
async def collection_jetable() -> AsyncIterator[str]:
    nom = f"test_ingest_{uuid.uuid4().hex[:8]}"
    try:
        yield nom
    finally:
        client = AsyncQdrantClient(url=settings.qdrant_url)
        try:
            if await client.collection_exists(nom):
                await client.delete_collection(nom)
        finally:
            await client.close()


async def test_le_corpus_de_reference_sindexe_et_se_retrouve(collection_jetable: str) -> None:
    """Chaine complete sur les vrais fichiers du depot.

    C'est le seul test qui verifie que `data/corpus` est reellement ingerable :
    encodage, extensions, taille. Un fichier ajoute au corpus et refuse par le
    chargeur ferait echouer ce test plutot que de disparaitre en silence.
    """
    embedder = SentenceTransformerEmbedder(
        settings.embedding_model,
        settings.embedding_dimension,
    )

    async with QdrantVectorStore(settings.qdrant_url, collection_jetable) as store:
        pipeline = IngestionPipeline(
            embedder,
            store,
            chunk_size=settings.chunk_size,
            chunk_overlap=settings.chunk_overlap,
            max_document_bytes=settings.max_document_bytes,
        )

        report = await pipeline.ingest_directory(_CORPUS)

        # Les quatre fichiers du corpus doivent tous passer, README compris.
        assert report.documents_ingested == 4
        assert report.skipped == ()
        assert report.chunks_indexed > 10

        question = await embedder.embed(
            ["Comment se defendre contre une injection de prompt indirecte ?"]
        )
        resultats = await store.search(question[0], k=3)

    assert len(resultats) == 3
    # La question porte sur l'injection indirecte : OWASP doit ressortir, pas
    # le cadre de gestion des risques du NIST.
    assert resultats[0].source == "owasp-llm-top10.md"
    assert all(resultat.text.strip() for resultat in resultats)
