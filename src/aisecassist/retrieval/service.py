"""Recherche vectorielle des extraits pertinents (ticket 11).

Ce module vectorise la question et interroge la base. Il **n'appelle pas le
modele de langage** : c'est la responsabilite de `generation/`. Cette separation
n'est pas cosmetique — elle permet de tester la pertinence de la recherche sans
faire tourner de modele, et de mesurer les deux etages independamment en M6.
"""

from __future__ import annotations

from aisecassist.embeddings.base import Embedder
from aisecassist.vectorstore.base import SearchResult, VectorStore


class RetrievalError(RuntimeError):
    """Echec de la recherche d'extraits."""


class RetrievalService:
    """Traduit une question en extraits du corpus."""

    def __init__(self, embedder: Embedder, store: VectorStore, default_k: int) -> None:
        self._embedder = embedder
        self._store = store
        self._default_k = default_k

    async def retrieve(self, question: str, k: int | None = None) -> list[SearchResult]:
        """Renvoie les extraits les plus proches de la question.

        Args:
            question: la question, deja validee par la couche API.
            k: nombre d'extraits ; la valeur de configuration par defaut sinon.

        Raises:
            RetrievalError: question vide, ou echec de vectorisation ou de recherche.
        """
        if not question.strip():
            # La couche API valide deja ce cas. Le controle est repete ici parce
            # que ce service sera aussi appele par l'agent en M3, qui lui passe
            # des arguments produits par un modele — donc non fiables.
            raise RetrievalError("La question est vide.")

        limite = self._default_k if k is None else k

        vectors = await self._embedder.embed([question])
        if not vectors:
            raise RetrievalError("La vectorisation de la question n'a produit aucun vecteur.")

        return await self._store.search(vectors[0], limite)
