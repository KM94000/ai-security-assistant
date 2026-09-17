"""Outils appelables par l'agent, et la validation de leurs arguments (SEC-05).

Un outil n'est pas une fonction Python exposee telle quelle. C'est un contrat :
un nom, une description destinee au modele, un schema d'arguments annonce, et
surtout une **validation cote code** de ce que le modele renvoie reellement.

Le schema annonce au modele n'est pas un controle : c'est une suggestion qu'il
suit ou non. Les arguments arrivent d'un modele influencable par la question de
l'utilisateur comme par les documents recuperes ; ils sont hostiles jusqu'a
validation. D'ou la regle : tout outil valide ses arguments avant d'agir, et
refuse plutot que de deviner.

**Moindre privilege (SEC-06)** : les outils de ce module sont en lecture seule.
Aucun n'ecrit, n'execute de commande, ni n'atteint le systeme de fichiers.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from aisecassist.llm.base import ToolSpec
from aisecassist.retrieval.service import RetrievalService
from aisecassist.security.limits import MAX_QUESTION_LENGTH
from aisecassist.security.prompt_sanitation import neutralize_markers, safe_source

AUCUN_EXTRAIT = "Aucun extrait pertinent dans le corpus pour cette question."
"""Observation rendue quand la recherche ne ramene rien.

C'est le pendant, cote agent, du seuil de pertinence (ADR-0010) : une phrase
explicite plutot qu'une liste vide, pour que le modele ait quelque chose a lire
et puisse conclure qu'il n'y a rien — au lieu de relancer indefiniment.
"""


class ToolArgumentError(ValueError):
    """Arguments refuses par la validation d'un outil.

    Erreur typee et non fatale : l'agent la transforme en observation rendue au
    modele. Un argument invalide est un evenement banal — le modele s'est
    trompe de forme — et ne doit pas faire tomber la requete.
    """


@dataclass(frozen=True, slots=True)
class ToolResult:
    """Ce qu'un outil rend : un texte pour le modele, et les sources citees."""

    observation: str
    sources: tuple[str, ...] = ()


class Tool(ABC):
    """Contrat commun a tous les outils de l'agent."""

    @property
    @abstractmethod
    def spec(self) -> ToolSpec:
        """Declaration presentee au modele."""

    @abstractmethod
    async def run(self, arguments: Mapping[str, Any]) -> ToolResult:
        """Execute l'outil apres validation de ses arguments.

        Raises:
            ToolArgumentError: arguments absents, malformes ou hors bornes.
        """


class _ArgumentsRecherche(BaseModel):
    """Forme exigee des arguments, quoi qu'annonce le modele.

    `extra="forbid"` : un argument non prevu fait echouer la validation au lieu
    d'etre ignore. Ignorer masquerait autant une erreur du modele qu'une
    tentative de passer un parametre auquel l'outil n'est pas cense obeir.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    question: str = Field(min_length=1, max_length=MAX_QUESTION_LENGTH)


class CorpusSearchTool(Tool):
    """Recherche des extraits dans le corpus indexe. Lecture seule.

    L'outil rend les extraits **assainis** : ce qui a la forme d'un delimiteur
    de bloc est neutralise, provenance comprise (SEC-01b, SEC-04). Le role
    `tool` du message separe deja la donnee de l'instruction ; la
    neutralisation est la seconde barriere, au cas ou un gabarit de conversation
    aplatirait les roles en un seul texte.
    """

    def __init__(self, retrieval: RetrievalService) -> None:
        self._retrieval = retrieval

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="rechercher_corpus",
            description=(
                "Recherche des extraits dans le corpus de referentiels de securite "
                "(OWASP LLM Top 10, MITRE ATLAS, NIST AI RMF). Renvoie des extraits "
                "sourcés, ou indique qu'aucun extrait pertinent n'existe. "
                "A utiliser pour toute question de fond : ne jamais repondre de memoire."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "question": {
                        "type": "string",
                        "description": "La question a rechercher, en langage naturel.",
                    }
                },
                "required": ["question"],
            },
        )

    async def run(self, arguments: Mapping[str, Any]) -> ToolResult:
        try:
            valides = _ArgumentsRecherche.model_validate(dict(arguments))
        except ValidationError as exc:
            # Le detail pydantic nomme le champ fautif sans reveler de valeur :
            # utile au modele pour se corriger, inoffensif dans un log.
            raise ToolArgumentError(
                f"Arguments refuses : {exc.error_count()} champ(s) invalide(s)."
            ) from exc

        resultats = await self._retrieval.retrieve(valides.question)
        if not resultats:
            return ToolResult(observation=AUCUN_EXTRAIT)

        extraits = [
            f"[{rang}] source : {safe_source(resultat.source)}\n"
            f"{neutralize_markers(resultat.text)}"
            for rang, resultat in enumerate(resultats, start=1)
        ]
        sources = tuple(dict.fromkeys(resultat.source for resultat in resultats))
        return ToolResult(observation="\n\n".join(extraits), sources=sources)
