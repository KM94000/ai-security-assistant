"""Assemblage des services et injection dans les routes.

Les clients HTTP et Qdrant sont crees une fois au demarrage et fermes a
l'arret. En creer un par requete ouvrirait une connexion a chaque appel, et
recharger le modele d'embeddings a chaque requete rendrait l'API inutilisable.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import cast

from fastapi import Request

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
    # Conserves pour pouvoir fermer leurs clients a l'arret ; les routes ne les
    # utilisent pas directement, elles passent par les deux services ci-dessus.
    store: QdrantVectorStore
    llm: OllamaProvider


def build_services() -> Services:
    """Construit les services a partir de la configuration."""
    embedder = SentenceTransformerEmbedder(
        settings.embedding_model,
        settings.embedding_dimension,
    )
    store = QdrantVectorStore(settings.qdrant_url, settings.qdrant_collection)
    llm = OllamaProvider(
        base_url=settings.ollama_base_url,
        model=settings.ollama_model,
        timeout_s=settings.llm_timeout_s,
    )

    return Services(
        retrieval=RetrievalService(embedder, store, settings.retrieval_top_k),
        generation=GenerationService(llm),
        store=store,
        llm=llm,
    )


async def close_services(services: Services) -> None:
    """Ferme les clients detenus par les services."""
    await services.store.aclose()
    await services.llm.aclose()


def get_services(request: Request) -> Services:
    """Dependance FastAPI : recupere les services attaches a l'application."""
    return cast(Services, request.app.state.services)
