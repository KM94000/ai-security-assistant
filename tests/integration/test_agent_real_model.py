"""Test d'acceptation du ticket 19 : l'agent choisit le RAG, et s'en sert.

Deselectionne par defaut. Exige Qdrant **et** Ollama :

    docker compose -f docker/docker-compose.yml up -d qdrant
    ollama serve
    pytest -m integration

Les tests unitaires verifient la boucle avec un modele scripte. Celui-ci
verifie la seule chose qu'un double ne peut pas prouver : que `llama3.1` emet
reellement un appel d'outil structure, qu'Ollama accepte nos messages de
resultat, et que la reponse finale s'appuie dessus.

**Lent par nature.** Un tour mesure environ 30 s pour la decision et 90 s pour
la redaction sur un CPU, d'ou le delai genereux ci-dessous : le plafond de
`llm_timeout_s` (120 s) est calibre pour `/query`, qui ne fait qu'un aller-retour.
Le reglage du delai propre a l'agent se fera au ticket 21, avec l'endpoint.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from pathlib import Path

import anyio
import pytest
from qdrant_client import AsyncQdrantClient

from aisecassist.agents.service import AgentAnswer, AgentService
from aisecassist.agents.tools import CorpusSearchTool
from aisecassist.config import settings
from aisecassist.embeddings.sentence_transformer import SentenceTransformerEmbedder
from aisecassist.ingestion.pipeline import IngestionPipeline
from aisecassist.llm.ollama import OllamaProvider
from aisecassist.retrieval.service import RetrievalService
from aisecassist.vectorstore.qdrant import QdrantVectorStore

pytestmark = [pytest.mark.integration, pytest.mark.llm]

_CORPUS = Path(__file__).resolve().parents[2] / "data" / "corpus"
_DELAI_AGENT_S = 600.0


def _embedder() -> SentenceTransformerEmbedder:
    return SentenceTransformerEmbedder(
        settings.embedding_model,
        settings.embedding_dimension,
        revision=settings.embedding_model_revision,
    )


def _store(collection: str) -> QdrantVectorStore:
    return QdrantVectorStore(
        settings.qdrant_url, collection, embedding_model=settings.embedding_model_id
    )


@pytest.fixture(scope="module")
def corpus_indexe() -> Iterator[str]:
    """Ingere le corpus une fois pour tout le module, dans une collection jetable."""
    nom = f"test_agent_{uuid.uuid4().hex[:8]}"

    async def _ingerer() -> None:
        async with _store(nom) as store:
            pipeline = IngestionPipeline(
                _embedder(),
                store,
                chunk_size=settings.chunk_size,
                chunk_overlap=settings.chunk_overlap,
                max_document_bytes=settings.max_document_bytes,
            )
            await pipeline.ingest_directory(_CORPUS)

    async def _supprimer() -> None:
        client = AsyncQdrantClient(url=settings.qdrant_url)
        try:
            if await client.collection_exists(nom):
                await client.delete_collection(nom)
        finally:
            await client.close()

    anyio.run(_ingerer)
    try:
        yield nom
    finally:
        anyio.run(_supprimer)


def _interroger(collection: str, question: str) -> AgentAnswer:
    async def _executer() -> AgentAnswer:
        async with (
            _store(collection) as store,
            OllamaProvider(
                base_url=settings.ollama_base_url,
                model=settings.ollama_model,
                timeout_s=_DELAI_AGENT_S,
            ) as provider,
        ):
            retrieval = RetrievalService(
                _embedder(),
                store,
                settings.retrieval_top_k,
                min_score=settings.retrieval_min_score,
            )
            agent = AgentService(
                provider,
                [CorpusSearchTool(retrieval)],
                max_iterations=settings.agent_max_iterations,
                max_answer_chars=settings.max_answer_chars,
            )
            return await agent.answer(question)

    return anyio.run(_executer)


def test_lagent_utilise_le_corpus_pour_une_question_de_fond(corpus_indexe: str) -> None:
    """Le critere d'acceptation du ticket 19 : l'agent appelle le RAG quand c'est pertinent.

    Les sources ne sont pas un ornement : elles ne peuvent provenir que d'un
    appel d'outil reellement execute. Leur presence prouve la boucle complete,
    du choix du modele jusqu'a l'observation rendue.
    """
    resultat = _interroger(
        corpus_indexe,
        "Comment se defendre contre une injection de prompt indirecte ?",
    )

    assert resultat.iterations >= 1
    assert resultat.sources
    assert resultat.answer.strip()


def test_hors_corpus_lagent_ne_cite_aucune_source(corpus_indexe: str) -> None:
    """Le seuil de pertinence (ADR-0010) traverse l'agent, et se voit dans les sources.

    L'agent peut toujours repondre de lui-meme — c'est le modele qui redige —
    mais il ne doit pas presenter de sources : la recherche n'a rien ramene, et
    une reponse faussement sourcee serait pire qu'une reponse sans source.
    """
    resultat = _interroger(corpus_indexe, "Quelle est la recette traditionnelle du cassoulet ?")

    assert resultat.sources == ()
    assert resultat.answer.strip()
