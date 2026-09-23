"""Assemblage des services et injection dans les routes.

Les clients HTTP et Qdrant sont crees une fois au demarrage et fermes a
l'arret. En creer un par requete ouvrirait une connexion a chaque appel, et
recharger le modele d'embeddings a chaque requete rendrait l'API inutilisable.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import cast

from fastapi import Request

from aisecassist.agents.cve import CveLookupTool
from aisecassist.agents.service import AgentService
from aisecassist.agents.tools import CorpusSearchTool
from aisecassist.config import settings
from aisecassist.embeddings.sentence_transformer import SentenceTransformerEmbedder
from aisecassist.generation.service import GenerationService
from aisecassist.llm.ollama import OllamaProvider
from aisecassist.retrieval.service import RetrievalService
from aisecassist.vectorstore.qdrant import QdrantVectorStore


@dataclass(frozen=True, slots=True)
class Services:
    """Services partages par toutes les requetes."""

    retrieval: RetrievalService
    generation: GenerationService
    agent: AgentService
    # Conserves pour pouvoir fermer leurs clients a l'arret ; les routes ne les
    # utilisent pas directement, elles passent par les services ci-dessus.
    store: QdrantVectorStore
    llm: OllamaProvider
    cve: CveLookupTool


def build_services() -> Services:
    """Construit les services a partir de la configuration."""
    embedder = SentenceTransformerEmbedder(
        settings.embedding_model,
        settings.embedding_dimension,
        revision=settings.embedding_model_revision,
    )
    store = QdrantVectorStore(
        settings.qdrant_url,
        settings.qdrant_collection,
        embedding_model=settings.embedding_model_id,
    )
    llm = OllamaProvider(
        base_url=settings.ollama_base_url,
        model=settings.ollama_model,
        timeout_s=settings.llm_timeout_s,
    )
    cve = CveLookupTool(
        base_url=settings.nvd_base_url,
        timeout_s=settings.nvd_timeout_s,
        api_key=settings.nvd_api_key,
        description_max_chars=settings.cve_description_max_chars,
    )
    retrieval = RetrievalService(
        embedder,
        store,
        settings.retrieval_top_k,
        min_score=settings.retrieval_min_score,
    )

    return Services(
        retrieval=retrieval,
        generation=GenerationService(llm, max_answer_chars=settings.max_answer_chars),
        # Le meme fournisseur que la generation : un seul client HTTP vers
        # Ollama, donc un seul endroit ou regler les delais et lire les erreurs.
        # Ce qui borne l'agent n'est pas le delai par appel mais son budget
        # total, porte par le service lui-meme.
        agent=AgentService(
            llm,
            [CorpusSearchTool(retrieval), cve],
            max_iterations=settings.agent_max_iterations,
            max_answer_chars=settings.max_answer_chars,
            timeout_s=settings.agent_timeout_s,
        ),
        store=store,
        llm=llm,
        cve=cve,
    )


async def close_services(services: Services) -> None:
    """Ferme les clients detenus par les services."""
    await services.store.aclose()
    await services.llm.aclose()
    await services.cve.aclose()


def get_services(request: Request) -> Services:
    """Dependance FastAPI : recupere les services attaches a l'application."""
    return cast(Services, request.app.state.services)
