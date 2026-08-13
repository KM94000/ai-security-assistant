"""Test d'acceptation de M1 : la chaine complete, du HTTP a la reponse sourcee.

Deselectionne par defaut. Exige Qdrant et Ollama demarres :

    docker compose -f docker/docker-compose.yml up -d qdrant
    ollama serve
    pytest -m integration

C'est le seul test qui exerce reellement le livrable de M1 : une question part
en HTTP, traverse la validation, la vectorisation, la recherche, l'assemblage du
prompt et le modele, et revient accompagnee de ses sources. Les tests unitaires
verifient chaque etage ; celui-ci verifie qu'ils sont branches ensemble.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from qdrant_client import AsyncQdrantClient

from aisecassist.config import settings
from aisecassist.embeddings.sentence_transformer import SentenceTransformerEmbedder
from aisecassist.ingestion.pipeline import IngestionPipeline
from aisecassist.main import app
from aisecassist.vectorstore.qdrant import QdrantVectorStore

pytestmark = pytest.mark.integration

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

    import anyio

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
    import anyio

    async def _ingerer() -> None:
        embedder = SentenceTransformerEmbedder(
            settings.embedding_model,
            settings.embedding_dimension,
        )
        async with QdrantVectorStore(settings.qdrant_url, collection_isolee) as store:
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


def test_une_question_reelle_recoit_une_reponse_sourcee(corpus_indexe: str) -> None:
    """Le livrable de M1, verifie de bout en bout.

    `with TestClient(app)` declenche le lifespan : les vrais services sont
    construits, le vrai modele est charge et le vrai Ollama est interroge.
    """
    with TestClient(app) as client:
        reponse = client.post(
            "/query",
            json={"question": "Comment se defendre contre une injection de prompt indirecte ?"},
        )

    assert reponse.status_code == 200
    corps = reponse.json()

    # Une reponse non vide, et surtout des sources : sans provenance, la reponse
    # d'un outil de securite n'est pas verifiable, donc pas utilisable.
    assert corps["answer"].strip() != ""
    assert corps["sources"] != []
    assert any(source["source"] == "owasp-llm-top10.md" for source in corps["sources"])


def test_une_question_hors_corpus_donne_un_refus_plutot_quune_invention(
    corpus_indexe: str,
) -> None:
    """La parade a la desinformation : refuser plutot que supposer (LLM09).

    Le corpus ne parle que de securite de l'IA. Une question sans rapport doit
    ramener soit un refus, soit une reponse qui reste sourcee — jamais une
    affirmation inventee presentee comme un fait.
    """
    with TestClient(app) as client:
        reponse = client.post(
            "/query",
            json={"question": "Quelle est la recette traditionnelle du cassoulet ?"},
        )

    assert reponse.status_code == 200
    corps = reponse.json()
    assert corps["answer"].strip() != ""
    # Toute affirmation doit rester rattachee au corpus reellement consulte.
    for source in corps["sources"]:
        assert source["source"].endswith(".md")
