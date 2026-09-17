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
    """Similarite avec la requete, entre -1 et 1 : plus elle est haute, plus l'extrait est proche.

    Le sens et l'echelle du score font partie du contrat. Le retrieval y applique
    un seuil de pertinence (ADR-0010) : une implementation qui renverrait une
    distance, ou plus bas vaut mieux, inverserait silencieusement le filtre.
    """


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


class CollectionEmbeddingModelMismatchError(VectorStoreError):
    """La collection a ete indexee avec un autre modele d'embeddings que celui configure.

    Le cas que le controle de dimension ne voit pas : deux modeles de meme
    dimension produisent des espaces vectoriels incomparables. La recherche
    repond alors sans la moindre erreur, en renvoyant des extraits choisis au
    hasard — et un seuil de pertinence calibre pour un modele n'a aucun sens
    pour l'autre (ADR-0010).

    Une collection qui ne declare aucun modele est traitee de la meme facon :
    rien ne permet de savoir avec quoi ses vecteurs ont ete produits. Comme pour
    la dimension, la remediation reste une decision humaine.
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
            CollectionEmbeddingModelMismatchError: la collection existe mais a
                ete indexee avec un autre modele, ou n'en declare aucun.
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
            CollectionEmbeddingModelMismatchError: la collection a ete indexee
                avec un autre modele.
            VectorStoreError: sequences de longueurs differentes, ou echec
                d'indexation.
        """

    @abstractmethod
    async def search(self, query_vector: Sequence[float], k: int) -> list[SearchResult]:
        """Renvoie les `k` extraits les plus proches, du plus proche au plus loin.

        Raises:
            CollectionEmbeddingModelMismatchError: les vecteurs de la collection
                ne viennent pas du modele configure.
            VectorStoreError: `k` invalide, base injoignable, ou point sans
                provenance exploitable.
        """
