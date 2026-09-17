"""Test d'integration : ingestion du vrai corpus dans le vrai Qdrant.

Deselectionne par defaut. Exige le conteneur demarre et telecharge le modele
d'embeddings :

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
        revision=settings.embedding_model_revision,
    )

    async with QdrantVectorStore(
        settings.qdrant_url, collection_jetable, embedding_model=settings.embedding_model_id
    ) as store:
        pipeline = IngestionPipeline(
            embedder,
            store,
            chunk_size=settings.chunk_size,
            chunk_overlap=settings.chunk_overlap,
            max_document_bytes=settings.max_document_bytes,
        )

        report = await pipeline.ingest_directory(_CORPUS)

        # Les trois referentiels doivent tous passer. La note de provenance vit
        # dans data/ et non dans data/corpus/, precisement pour ne pas etre
        # indexee comme du contenu interrogeable.
        assert report.documents_ingested == 3
        assert report.skipped == ()
        assert report.chunks_indexed > 10

        question = await embedder.embed(
            ["Comment se defendre contre une injection de prompt indirecte ?"]
        )
        resultats = await store.search(question[0], k=3)

    assert len(resultats) == 3
    # La question porte sur l'injection indirecte, que traitent OWASP (LLM01) et
    # MITRE ATLAS (« Techniques particulierement pertinentes pour un RAG »). Le
    # cadre du NIST, qui n'en parle pas, ne doit pas ressortir en tete. Exiger
    # OWASP devant ATLAS figerait un ordre entre deux passages pertinents : c'est
    # ce qu'a revele le changement de modele (ADR-0010), sans que la recherche
    # soit moins bonne.
    assert resultats[0].source in {"owasp-llm-top10.md", "mitre-atlas.md"}
    assert "owasp-llm-top10.md" in {resultat.source for resultat in resultats}
    assert all(resultat.text.strip() for resultat in resultats)
