"""Generation de la reponse a partir des extraits recuperes (tickets 12 et 14)."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass

from aisecassist.generation.prompt import REFUS_SANS_CONTEXTE, build_prompt
from aisecassist.llm.base import LLMError, LLMProvider
from aisecassist.vectorstore.base import SearchResult

logger = logging.getLogger(__name__)

MARQUEUR_TRONCATURE = "\n\n[reponse tronquee : plafond de longueur atteint]"
"""Marqueur ajoute quand le plafond est atteint.

Tronquer en silence laisserait l'utilisateur devant une reponse coupee au
milieu d'une phrase, sans savoir si le modele a fini, si la connexion a lache,
ou si le serveur a decide d'arreter. Le dire coute une ligne.
"""


@dataclass(frozen=True, slots=True)
class GeneratedAnswer:
    """Reponse produite, accompagnee des sources qui l'ont alimentee."""

    answer: str
    sources: tuple[str, ...]


class GenerationService:
    """Assemble le prompt et interroge le modele."""

    def __init__(self, llm: LLMProvider, *, max_answer_chars: int) -> None:
        self._llm = llm
        self._max_answer_chars = max_answer_chars

    async def answer(self, question: str, results: Sequence[SearchResult]) -> GeneratedAnswer:
        """Produit une reponse fondee sur les extraits fournis.

        Sans extrait, le modele n'est pas appele du tout : on renvoie un refus
        explicite. Interroger un modele avec un contexte vide revient a lui
        demander de repondre de memoire, ce qui est exactement le mode de
        defaillance qu'un RAG est cense supprimer (LLM09, desinformation).
        C'est aussi un appel de moins a payer.

        Raises:
            LLMError: le fournisseur est injoignable, en erreur, ou muet.
        """
        if not results:
            return GeneratedAnswer(answer=REFUS_SANS_CONTEXTE, sources=())

        prompt = build_prompt(question, results)
        reponse = (await self._llm.complete(prompt.text)).strip()

        # Une reponse vide accompagnee de sources est plus trompeuse qu'une
        # erreur : elle a la forme d'un resultat verifiable et n'affirme rien.
        # On la traite comme ce qu'elle est — un echec de generation — et la
        # couche API la rend en 503.
        if not reponse:
            raise LLMError("Le modele n'a produit aucun texte exploitable.")

        return GeneratedAnswer(answer=self._plafonner(reponse), sources=prompt.sources)

    async def stream_answer(
        self, question: str, results: Sequence[SearchResult]
    ) -> AsyncIterator[str]:
        """Produit la reponse par fragments, au fil de la generation.

        Meme contrat que `answer` sur le fond : sans extrait, le modele n'est
        pas appele et le refus est emis tel quel.

        Le plafond de longueur est applique **cote serveur**, fragment par
        fragment. C'est le seul endroit ou il protege : une generation qui part
        en boucle emettrait sinon des fragments indefiniment, et rien du cote
        client ne l'arreterait (SEC-10).

        Raises:
            LLMError: le fournisseur est injoignable ou en erreur.
        """
        if not results:
            yield REFUS_SANS_CONTEXTE
            return

        prompt = build_prompt(question, results)
        emis = 0

        async for fragment in self._llm.stream(prompt.text):
            if not fragment:
                continue

            # Le plafond est deja atteint et il reste des fragments : du contenu
            # a donc bien ete coupe.
            if emis >= self._max_answer_chars:
                self._signaler_troncature()
                yield MARQUEUR_TRONCATURE
                return

            restant = self._max_answer_chars - emis
            # `>` et non `>=` : un fragment qui remplit exactement l'espace
            # restant n'est pas tronque. Si le flux s'arrete la, la reponse est
            # complete et annoncer une troncature serait faux.
            if len(fragment) > restant:
                self._signaler_troncature()
                yield fragment[:restant]
                yield MARQUEUR_TRONCATURE
                return

            emis += len(fragment)
            yield fragment

    def _plafonner(self, reponse: str) -> str:
        """Applique le meme plafond a une reponse complete."""
        if len(reponse) <= self._max_answer_chars:
            return reponse
        self._signaler_troncature()
        return reponse[: self._max_answer_chars] + MARQUEUR_TRONCATURE

    def _signaler_troncature(self) -> None:
        logger.warning(
            "Reponse tronquee a %d caracteres : plafond max_answer_chars atteint.",
            self._max_answer_chars,
        )
