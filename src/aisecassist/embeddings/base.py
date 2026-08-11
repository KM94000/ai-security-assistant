"""Interface abstraite de vectorisation de texte (ADR-0002).

La meme instance alimente l'ingestion et la recherche : question et documents
doivent vivre dans le meme espace vectoriel, sinon la recherche est du bruit.
"""

from abc import ABC, abstractmethod
from collections.abc import Sequence


class EmbedderError(RuntimeError):
    """Echec de la vectorisation."""


class DimensionMismatchError(EmbedderError):
    """Le modele charge ne produit pas la dimension attendue par la configuration.

    Cette erreur est volontairement fatale plutot que journalisee.

    Un modele produisant 768 dimensions face a une collection Qdrant creee pour
    384 ne provoque aucune alerte visible a l'usage : selon les cas l'indexation
    est rejetee, ou bien la recherche continue de repondre en renvoyant des
    resultats silencieusement incoherents. C'est le pire mode de defaillance
    d'un RAG, parce qu'il ressemble a un simple probleme de qualite. Mieux vaut
    refuser de demarrer (SECURITY.md, piege n.4).
    """


class Embedder(ABC):
    """Transforme du texte en vecteurs."""

    @property
    @abstractmethod
    def dimension(self) -> int:
        """Nombre de composantes des vecteurs produits.

        Sert a creer la collection vectorielle avec la bonne taille.
        """

    @abstractmethod
    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """Vectorise des textes et renvoie un vecteur par texte, dans l'ordre recu.

        L'ordre est contractuel : l'appelant reassocie chaque vecteur a son
        texte par position.

        Raises:
            EmbedderError: le modele est indisponible ou incoherent.
        """
