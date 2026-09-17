"""Recherche vectorielle des extraits pertinents (ticket 11, ADR-0010).

Ce module vectorise la question et interroge la base. Il **n'appelle pas le
modele de langage** : c'est la responsabilite de `generation/`. Cette separation
n'est pas cosmetique — elle permet de tester la pertinence de la recherche sans
faire tourner de modele, et de mesurer les deux etages independamment en M6.
"""

from __future__ import annotations

import logging

from aisecassist.embeddings.base import Embedder
from aisecassist.vectorstore.base import SearchResult, VectorStore

logger = logging.getLogger(__name__)


class RetrievalError(RuntimeError):
    """Echec de la recherche d'extraits."""


class RetrievalService:
    """Traduit une question en extraits du corpus."""

    def __init__(
        self,
        embedder: Embedder,
        store: VectorStore,
        default_k: int,
        *,
        min_score: float,
    ) -> None:
        self._embedder = embedder
        self._store = store
        self._default_k = default_k
        self._min_score = min_score

    async def retrieve(self, question: str, k: int | None = None) -> list[SearchResult]:
        """Renvoie les extraits les plus proches de la question, s'ils sont assez proches.

        Une recherche top-k seule ne sait pas dire « je n'ai rien » : elle renvoie
        toujours ses k voisins, meme pour une question sans aucun rapport avec le
        corpus. Le refus prevu par la generation ne se declenchait donc jamais, et
        un agent qui s'appuierait sur ce service tournerait sur des extraits hors
        sujet. D'ou le seuil : un extrait dont le score n'atteint pas `min_score`
        est ecarte, et une liste vide signifie que le corpus ne couvre pas la
        question.

        Le seuil trie le pertinent du hors-sujet, pas le couvert du non couvert :
        une question de securite absente du corpus peut le franchir. Ce n'est pas
        non plus un controle de securite — un document concu pour ressembler a des
        questions courantes le franchit par construction. Sa valeur depend du
        modele d'embeddings qui l'a calibre (ADR-0010).

        Args:
            question: la question, deja validee par la couche API.
            k: nombre maximal d'extraits ; la valeur de configuration par defaut sinon.

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

        resultats = await self._store.search(vectors[0], limite)
        pertinents = [resultat for resultat in resultats if resultat.score >= self._min_score]

        if resultats and not pertinents:
            # Journalise sans la question, qui peut contenir des donnees sensibles.
            # Le meilleur score suffit a recalibrer le seuil si les refus a tort
            # se multiplient.
            logger.info(
                "Aucun extrait n'atteint le seuil de pertinence : meilleur score %.3f, seuil %.3f.",
                max(resultat.score for resultat in resultats),
                self._min_score,
            )
        return pertinents
