"""Implementation de `VectorStore` adossee a Qdrant (ADR-0005)."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Sequence
from types import TracebackType
from typing import Any

from qdrant_client import AsyncQdrantClient, models

from aisecassist.vectorstore.base import (
    CollectionDimensionMismatchError,
    CollectionEmbeddingModelMismatchError,
    SearchResult,
    VectorStore,
    VectorStoreError,
)

# Namespace fixe servant a deriver les identifiants de points. Deux ingestions
# du meme extrait issu de la meme source produisent le meme identifiant, donc
# une mise a jour et non un doublon. Sans cela, re-ingerer un corpus le
# dupliquerait, et la recherche renverrait plusieurs fois le meme passage en
# gaspillant le budget de contexte.
_POINT_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_DNS, "vectorstore.aisecassist")

# Cle des metadonnees de collection ou est inscrit le modele d'embeddings.
_CLE_MODELE = "embedding_model"

logger = logging.getLogger(__name__)


class QdrantVectorStore(VectorStore):
    """Range les vecteurs dans une collection Qdrant.

    Le client est injectable : les tests utilisent `AsyncQdrantClient(":memory:")`,
    qui execute le vrai moteur Qdrant en memoire. On teste donc le comportement
    reel de la base, sans conteneur ni reseau.

    Le store est lie a un modele d'embeddings, identifie jusqu'a la revision de
    ses poids. Il l'inscrit dans chaque collection qu'il cree, et refuse de
    travailler sur une collection qui en declare un autre — ou aucun (ADR-0010).
    """

    def __init__(
        self,
        url: str,
        collection: str,
        *,
        embedding_model: str,
        client: AsyncQdrantClient | None = None,
    ) -> None:
        self._collection = collection
        self._embedding_model = embedding_model
        self._owns_client = client is None
        self._client = client or AsyncQdrantClient(url=url)
        # Le modele n'est verifie qu'une fois par instance, et seulement quand la
        # verification reussit. Une collection recreee pendant que l'API tourne
        # est donc acceptee a la requete suivante, sans redemarrage.
        self._modele_verifie = False

    async def ensure_collection(self, dimension: int) -> None:
        try:
            exists = await self._client.collection_exists(self._collection)
        except Exception as exc:
            raise VectorStoreError(f"Qdrant injoignable : {exc}") from exc

        if not exists:
            try:
                await self._client.create_collection(
                    self._collection,
                    vectors_config=models.VectorParams(
                        size=dimension,
                        distance=models.Distance.COSINE,
                    ),
                    # Inscrit dans la collection elle-meme : c'est le seul endroit
                    # ou l'information survit a la configuration qui l'a produite.
                    metadata={_CLE_MODELE: self._embedding_model},
                )
            except Exception as exc:
                raise VectorStoreError(
                    f"Creation de la collection {self._collection} echouee : {exc}"
                ) from exc
            self._modele_verifie = True
            return

        configuration = await self._lire_configuration()
        actual = self._dimension(configuration)
        if actual != dimension:
            raise CollectionDimensionMismatchError(
                f"La collection {self._collection} attend des vecteurs de {actual} "
                f"dimensions, or l'embedder en produit {dimension}. "
                "Recreer la collection et re-ingerer, ou corriger embedding_model."
            )
        self._verifier_modele(configuration)

    async def add(
        self,
        texts: Sequence[str],
        vectors: Sequence[Sequence[float]],
        sources: Sequence[str],
    ) -> None:
        # Des sequences desalignees n'echouent pas d'elles-memes : elles
        # associeraient un extrait a la provenance d'un autre. La reponse
        # citerait alors une source qui ne contient pas ce qu'elle affirme.
        if not (len(texts) == len(vectors) == len(sources)):
            raise VectorStoreError(
                "Sequences desalignees : "
                f"{len(texts)} textes, {len(vectors)} vecteurs, {len(sources)} sources."
            )
        if not texts:
            return

        # Ecrire dans l'espace d'un autre modele serait pire que d'y lire : le
        # melange resterait en base, et plus rien ne permettrait de le demeler.
        await self._exiger_le_modele_configure()

        points = [
            models.PointStruct(
                id=_point_id(source, text),
                vector=[float(component) for component in vector],
                payload={"text": text, "source": source},
            )
            for text, vector, source in zip(texts, vectors, sources, strict=True)
        ]

        try:
            await self._client.upsert(self._collection, points=points)
        except Exception as exc:
            raise VectorStoreError(f"Indexation dans {self._collection} echouee : {exc}") from exc

    async def search(self, query_vector: Sequence[float], k: int) -> list[SearchResult]:
        if k <= 0:
            raise VectorStoreError(f"k doit etre strictement positif, recu {k}.")

        # L'API ne passe jamais par `ensure_collection` : sans ce controle, une
        # collection indexee avec un autre modele serait interrogee sans erreur.
        await self._exiger_le_modele_configure()

        try:
            response = await self._client.query_points(
                self._collection,
                query=[float(component) for component in query_vector],
                limit=k,
            )
        except Exception as exc:
            raise VectorStoreError(f"Recherche dans {self._collection} echouee : {exc}") from exc

        # Un point sans provenance est ecarte, pas fatal. Le faire echouer
        # transformait une seule donnee corrompue en panne totale : si ce point
        # se trouvait pres du centre de l'espace vectoriel, il entrait dans le
        # top-k de presque toutes les requetes et /query renvoyait 503 pour tout
        # le monde. La propriete de securite est preservee — aucun extrait sans
        # provenance n'est rendu — mais la disponibilite ne depend plus de
        # l'integrite de chaque point.
        resultats: list[SearchResult] = []
        for point in response.points:
            resultat = _to_search_result(point)
            if resultat is None:
                logger.warning(
                    "Point %s ecarte de %s : provenance inexploitable dans le payload.",
                    getattr(point, "id", "?"),
                    self._collection,
                )
                continue
            resultats.append(resultat)
        return resultats

    async def aclose(self) -> None:
        """Libere le client si ce store en est proprietaire."""
        if self._owns_client:
            await self._client.close()

    async def __aenter__(self) -> QdrantVectorStore:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.aclose()

    async def _exiger_le_modele_configure(self) -> None:
        """Verifie le modele declare par la collection, sauf si c'est deja fait."""
        if not self._modele_verifie:
            self._verifier_modele(await self._lire_configuration())

    async def _lire_configuration(self) -> models.CollectionConfig:
        """Lit la configuration de la collection existante."""
        try:
            info = await self._client.get_collection(self._collection)
        except Exception as exc:
            raise VectorStoreError(
                f"Lecture de la collection {self._collection} echouee : {exc}"
            ) from exc
        return info.config

    def _dimension(self, configuration: models.CollectionConfig) -> int:
        """Extrait la dimension declaree par la collection."""
        params = configuration.params.vectors
        if not isinstance(params, models.VectorParams):
            raise VectorStoreError(
                f"La collection {self._collection} utilise des vecteurs nommes ; "
                "cette configuration n'est pas prise en charge."
            )
        return params.size

    def _verifier_modele(self, configuration: models.CollectionConfig) -> None:
        """Refuse une collection dont les vecteurs ne viennent pas du modele configure."""
        declare = (configuration.metadata or {}).get(_CLE_MODELE)
        if declare == self._embedding_model:
            self._modele_verifie = True
            return

        if declare is None:
            raise CollectionEmbeddingModelMismatchError(
                f"La collection {self._collection} ne declare pas le modele d'embeddings "
                "qui a produit ses vecteurs : elle est anterieure a l'ADR-0010. Rien ne "
                f"garantit qu'ils soient comparables a ceux de {self._embedding_model}. "
                "Recreer la collection et re-ingerer."
            )
        raise CollectionEmbeddingModelMismatchError(
            f"La collection {self._collection} a ete indexee avec {declare}, or la "
            f"configuration utilise {self._embedding_model}. A dimension egale, deux "
            "modeles produisent des espaces incomparables : la recherche repondrait sans "
            "erreur, mais au hasard. Recreer la collection et re-ingerer, ou realigner "
            "EMBEDDING_MODEL et EMBEDDING_MODEL_REVISION."
        )


def _point_id(source: str, text: str) -> str:
    """Derive un identifiant reproductible a partir de la provenance et du texte.

    Le separateur nul evite les collisions entre couples differents dont la
    concatenation serait identique.
    """
    return str(uuid.uuid5(_POINT_NAMESPACE, f"{source}\x00{text}"))


def _to_search_result(point: Any) -> SearchResult | None:
    """Convertit un point Qdrant en `SearchResult`, ou `None` si sa provenance manque.

    Un point sans `text` ni `source` exploitables n'est jamais rendu avec des
    valeurs par defaut : un extrait cite comme provenant de "inconnu" au milieu
    d'une reponse est pire qu'un extrait absent, parce qu'il a l'air verifiable
    (SEC-08). L'appelant l'ecarte et le journalise.
    """
    payload = point.payload or {}
    text = payload.get("text")
    source = payload.get("source")
    if not isinstance(text, str) or not isinstance(source, str):
        return None
    return SearchResult(text=text, source=source, score=float(point.score))
