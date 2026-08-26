"""Generation de la reponse a partir des extraits recuperes (tickets 12 et 14)."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass

from aisecassist.generation.prompt import REFUS_SANS_CONTEXTE, build_prompt
from aisecassist.llm.base import LLMError, LLMProvider
from aisecassist.security.output_guardrail import StreamRedactor, redact
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

        # Le nonce est passe en litteral : le modele n'a aucune raison de le
        # restituer, et le laisser passer revelerait la structure de la cloture.
        assainie = redact(self._plafonner(reponse), literaux=(prompt.nonce,))
        self._signaler_fuite(assainie.categories)

        return GeneratedAnswer(answer=assainie.text, sources=prompt.sources)

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
        redacteur = StreamRedactor(literaux=(prompt.nonce,))
        emis = 0
        tronque = False

        async for fragment in self._llm.stream(prompt.text):
            if not fragment:
                continue

            # Le plafond est deja atteint et il reste des fragments : du contenu
            # a donc bien ete coupe.
            if emis >= self._max_answer_chars:
                tronque = True
                break

            restant = self._max_answer_chars - emis
            # `>` et non `>=` : un fragment qui remplit exactement l'espace
            # restant n'est pas tronque. Si le flux s'arrete la, la reponse est
            # complete et annoncer une troncature serait faux.
            if len(fragment) > restant:
                fragment = fragment[:restant]
                tronque = True

            emis += len(fragment)
            # Le plafond porte sur ce que le modele a produit, la redaction sur
            # ce qui sort. Les deux ne se compensent pas : rediger d'abord
            # permettrait a un secret long de consommer le budget a la place du
            # contenu utile.
            sortie = redacteur.feed(fragment)
            if sortie:
                yield sortie

            if tronque:
                break

        # Le reliquat retenu par la fenetre de securite ne doit pas etre perdu.
        reliquat = redacteur.flush()
        if reliquat:
            yield reliquat

        self._signaler_fuite(redacteur.categories)

        if tronque:
            self._signaler_troncature()
            yield MARQUEUR_TRONCATURE

    def _plafonner(self, reponse: str) -> str:
        """Applique le meme plafond a une reponse complete."""
        if len(reponse) <= self._max_answer_chars:
            return reponse
        self._signaler_troncature()
        return reponse[: self._max_answer_chars] + MARQUEUR_TRONCATURE

    def _signaler_fuite(self, categories: Sequence[str]) -> None:
        """Journalise un declenchement du guardrail, sans jamais la valeur.

        Un declenchement est anormal : un secret ne devrait pas atteindre le
        modele. Le signal merite donc un avertissement, pas une ligne de debug
        noyee dans le flux.
        """
        if categories:
            logger.warning(
                "Guardrail de sortie declenche : %s. Un secret a atteint le modele, "
                "ce qui signale une defaillance en amont.",
                ", ".join(categories),
            )

    def _signaler_troncature(self) -> None:
        logger.warning(
            "Reponse tronquee a %d caracteres : plafond max_answer_chars atteint.",
            self._max_answer_chars,
        )
