"""Interface abstraite d'un fournisseur de modele de langage.

Le code metier ne depend que de cette abstraction (ADR-0002). Basculer d'Ollama
vers OpenAI ne doit toucher aucun module de generation, et les tests doivent
pouvoir substituer un double sans qu'aucun modele ne tourne.
"""

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator


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
