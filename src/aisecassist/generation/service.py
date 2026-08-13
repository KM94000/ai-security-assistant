"""Generation de la reponse a partir des extraits recuperes (ticket 12)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from aisecassist.generation.prompt import REFUS_SANS_CONTEXTE, build_prompt
from aisecassist.llm.base import LLMProvider
from aisecassist.vectorstore.base import SearchResult


@dataclass(frozen=True, slots=True)
class GeneratedAnswer:
    """Reponse produite, accompagnee des sources qui l'ont alimentee."""

    answer: str
    sources: tuple[str, ...]


class GenerationService:
    """Assemble le prompt et interroge le modele."""

    def __init__(self, llm: LLMProvider) -> None:
        self._llm = llm

    async def answer(self, question: str, results: Sequence[SearchResult]) -> GeneratedAnswer:
        """Produit une reponse fondee sur les extraits fournis.

        Sans extrait, le modele n'est pas appele du tout : on renvoie un refus
        explicite. Interroger un modele avec un contexte vide revient a lui
        demander de repondre de memoire, ce qui est exactement le mode de
        defaillance qu'un RAG est cense supprimer (LLM09, desinformation).
        C'est aussi un appel de moins a payer.

        Raises:
            LLMError: le fournisseur est injoignable ou en erreur.
        """
        if not results:
            return GeneratedAnswer(answer=REFUS_SANS_CONTEXTE, sources=())

        prompt = build_prompt(question, results)
        reponse = await self._llm.complete(prompt.text)

        return GeneratedAnswer(answer=reponse.strip(), sources=prompt.sources)
