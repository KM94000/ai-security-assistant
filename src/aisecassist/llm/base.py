"""Interface abstraite d'un fournisseur de modele de langage.

Le code metier ne depend que de cette abstraction (ADR-0002). Basculer d'Ollama
vers OpenAI ne doit toucher aucun module de generation, et les tests doivent
pouvoir substituer un double sans qu'aucun modele ne tourne.

Deux interfaces, et pas une seule : `LLMProvider` suffit a `/query`, qui envoie
un prompt et lit du texte. L'agent a besoin de davantage — presenter des outils
au modele et recevoir un appel structure — d'ou `ToolCallingProvider`
(ADR-0011). Les garder separees evite d'exiger d'un fournisseur une capacite
dont la moitie du produit n'a pas l'usage.
"""

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal


class LLMError(RuntimeError):
    """Echec d'un appel au fournisseur de modele.

    Erreur typee plutot que l'exception brute du client HTTP : le metier n'a pas
    a connaitre la bibliotheque utilisee par l'implementation, et la couche API
    doit pouvoir distinguer cette panne d'une erreur de validation d'entree.

    Le message peut contenir des details techniques : il est destine aux logs,
    jamais renvoye tel quel au client (CLAUDE.md, section 6).
    """


class LLMProvider(ABC):
    """Fournisseur de completion de texte."""

    @abstractmethod
    async def complete(self, prompt: str) -> str:
        """Renvoie la reponse complete du modele.

        Args:
            prompt: le prompt deja assemble. Cette couche ne construit ni ne
                valide le prompt : c'est la responsabilite de `generation/`.

        Raises:
            LLMError: fournisseur injoignable, en erreur, ou reponse inattendue.
        """

    @abstractmethod
    def stream(self, prompt: str) -> AsyncIterator[str]:
        """Renvoie la reponse par fragments, au fil de la generation.

        Args:
            prompt: voir `complete`.

        Raises:
            LLMError: fournisseur injoignable, en erreur, ou reponse inattendue.
        """


Role = Literal["system", "user", "assistant", "tool"]


@dataclass(frozen=True, slots=True)
class ChatMessage:
    """Un tour de conversation, tel qu'il est presente au modele."""

    role: Role
    content: str
    tool_name: str | None = None
    """Nom de l'outil dont ce message porte le resultat, pour `role="tool"`."""

    tool_calls: tuple["ToolCall", ...] = field(default_factory=tuple)
    """Appels demandes par le modele, pour `role="assistant"`.

    Conserves dans l'historique : sans eux, le resultat d'outil qui suit
    arriverait sans la demande qui l'a provoque, et le modele pourrait
    redemander la meme chose indefiniment.
    """


@dataclass(frozen=True, slots=True)
class ToolSpec:
    """Declaration d'un outil offerte au modele.

    `parameters` est un schema JSON. C'est une description, pas un controle :
    rien ne garantit que le modele s'y conforme, et la validation reelle des
    arguments se fait cote code avant execution (SEC-05).
    """

    name: str
    description: str
    parameters: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class ToolCall:
    """Appel d'outil demande par le modele.

    **Contenu hostile jusqu'a validation.** Le nom comme les arguments sont
    produits par un modele, lui-meme influencable par la question de
    l'utilisateur et par les documents recuperes. Ils ne sont ni verifies ni
    filtres a ce niveau : l'appelant doit verifier que l'outil est autorise,
    puis valider les arguments avant toute execution (SEC-05, SEC-06).
    """

    name: str
    arguments: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class ChatReply:
    """Reponse du modele : du texte, des appels d'outils, ou les deux."""

    text: str
    tool_calls: tuple[ToolCall, ...] = field(default_factory=tuple)


class ToolCallingProvider(ABC):
    """Fournisseur capable de conduire une conversation avec des outils."""

    @abstractmethod
    async def chat(
        self,
        messages: Sequence[ChatMessage],
        tools: Sequence[ToolSpec],
    ) -> ChatReply:
        """Poursuit la conversation et renvoie la reaction du modele.

        L'implementation transmet et traduit ; elle ne decide rien. Elle
        n'execute aucun outil, n'en refuse aucun et ne valide aucun argument :
        ces decisions appartiennent a l'agent, qui detient la liste des outils
        autorises et leurs regles de validation.

        Args:
            messages: l'historique, du plus ancien au plus recent.
            tools: les outils presentes au modele pour ce tour.

        Raises:
            LLMError: fournisseur injoignable, en erreur, ou reponse inattendue.
        """
