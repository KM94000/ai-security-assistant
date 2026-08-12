"""Interface abstraite de la base vectorielle (ADR-0002, ADR-0005)."""

from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SearchResult:
    """Extrait retrouve, accompagne de sa provenance et de son score.

    `source` n'est pas un ornement. C'est ce qui permet de citer l'origine d'une
    reponse, et de remonter d'un contenu suspect jusqu'au document qui l'a
    introduit dans le corpus (SECURITY.md, SEC-08). Un extrait sans provenance
    est inexploitable : on ne peut ni le verifier ni le retirer.
    """

    text: str
    source: str
    score: float


class VectorStoreError(RuntimeError):
    """Echec d'une operation sur la base vectorielle.

    Erreur typee : le metier n'a pas a connaitre le client Qdrant, et la couche
    API doit pouvoir distinguer cette panne d'une erreur de validation.
    """


class CollectionDimensionMismatchError(VectorStoreError):
    """La collection existante n'a pas la dimension demandee.

    Volontairement fatale. Reutiliser une collection creee pour une autre
    dimension conduit soit au rejet des insertions, soit a une recherche qui
    repond quand meme en renvoyant n'importe quoi. Le second cas est le plus
    dangereux : il ressemble a un simple probleme de pertinence.

    La remediation n'est jamais automatique — recreer la collection detruirait
    des donnees. C'est une decision humaine (ADR-0005).
    """


class VectorStore(ABC):
    """Range des vecteurs et retrouve les plus proches d'une requete."""

    @abstractmethod
    async def ensure_collection(self, dimension: int) -> None:
        """Cree la collection si elle n'existe pas, sans rien detruire.

        Idempotent : appeler la methode sur une collection deja conforme ne
        fait rien.

        Raises:
            CollectionDimensionMismatchError: la collection existe avec une
                autre dimension.
            VectorStoreError: la base est injoignable ou en erreur.
        """

    @abstractmethod
    async def add(
        self,
        texts: Sequence[str],
        vectors: Sequence[Sequence[float]],
        sources: Sequence[str],
    ) -> None:
        """Indexe des extraits avec leurs vecteurs et leur provenance.

        Les trois sequences sont paralleles : `texts[i]`, `vectors[i]` et
        `sources[i]` decrivent le meme extrait.

        Raises:
            VectorStoreError: sequences de longueurs differentes, ou echec
                d'indexation.
        """

    @abstractmethod
    async def search(self, query_vector: Sequence[float], k: int) -> list[SearchResult]:
        """Renvoie les `k` extraits les plus proches, du plus proche au plus loin.

        Raises:
            VectorStoreError: `k` invalide, base injoignable, ou point sans
                provenance exploitable.
        """
