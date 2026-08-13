"""Tests d'integration contre le vrai conteneur Qdrant.

Deselectionnes par defaut. Exigent le service demarre :

    docker compose -f docker/docker-compose.yml up -d qdrant
    pytest -m integration

Chaque test travaille dans une collection jetable, supprimee ensuite : la
collection de travail ne doit jamais etre polluee par la suite de tests.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest
from qdrant_client import AsyncQdrantClient

from aisecassist.config import settings
from aisecassist.embeddings.sentence_transformer import SentenceTransformerEmbedder
from aisecassist.vectorstore.base import CollectionDimensionMismatchError
from aisecassist.vectorstore.qdrant import QdrantVectorStore

pytestmark = [pytest.mark.anyio, pytest.mark.integration]


@pytest.fixture
async def collection_jetable() -> AsyncIterator[str]:
    nom = f"test_m1_{uuid.uuid4().hex[:8]}"
    try:
        yield nom
    finally:
        client = AsyncQdrantClient(url=settings.qdrant_url)
        try:
            if await client.collection_exists(nom):
                await client.delete_collection(nom)
        finally:
            await client.close()


async def test_ensure_collection_cree_puis_detecte_un_conflit(collection_jetable: str) -> None:
    """Le garde-fou de dimension doit tenir face au vrai moteur, pas seulement en memoire."""
    async with QdrantVectorStore(settings.qdrant_url, collection_jetable) as store:
        await store.ensure_collection(settings.embedding_dimension)
        await store.ensure_collection(settings.embedding_dimension)  # idempotent

        with pytest.raises(CollectionDimensionMismatchError):
            await store.ensure_collection(settings.embedding_dimension + 1)


async def test_chaine_complete_vectoriser_indexer_retrouver(collection_jetable: str) -> None:
    """Bout en bout : MiniLM vectorise, Qdrant indexe, la recherche retrouve par le sens.

    C'est le substrat du RAG. Si ce test passe, il ne manque plus que
    l'assemblage du prompt et l'appel au modele pour repondre a une question.
    """
    embedder = SentenceTransformerEmbedder(
        settings.embedding_model,
        settings.embedding_dimension,
    )
    textes = [
        "Une injection de prompt indirecte passe par un document ingere par le systeme.",
        "La tarte aux pommes se prepare avec une pate brisee et des fruits emincés.",
    ]
    sources = ["owasp-llm-top10.md", "recettes.md"]

    async with QdrantVectorStore(settings.qdrant_url, collection_jetable) as store:
        await store.ensure_collection(embedder.dimension)
        await store.add(textes, await embedder.embed(textes), sources)

        question = await embedder.embed(["comment fonctionne une injection de prompt ?"])
        results = await store.search(question[0], k=1)

    # La recherche doit ramener le document pertinent, pas le premier venu :
    # c'est la difference entre un index qui fonctionne et un index qui repond.
    assert len(results) == 1
    assert results[0].source == "owasp-llm-top10.md"
