"""Implementation de `VectorStore` adossee a Qdrant (ADR-0005)."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from types import TracebackType
from typing import Any

from qdrant_client import AsyncQdrantClient, models

from aisecassist.vectorstore.base import (
    CollectionDimensionMismatchError,
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


class QdrantVectorStore(VectorStore):
    """Range les vecteurs dans une collection Qdrant.

    Le client est injectable : les tests utilisent `AsyncQdrantClient(":memory:")`,
    qui execute le vrai moteur Qdrant en memoire. On teste donc le comportement
    reel de la base, sans conteneur ni reseau.
    """

    def __init__(
        self,
        url: str,
        collection: str,
        client: AsyncQdrantClient | None = None,
    ) -> None:
        self._collection = collection
        self._owns_client = client is None
        self._client = client or AsyncQdrantClient(url=url)

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
                )
            except Exception as exc:
                raise VectorStoreError(
                    f"Creation de la collection {self._collection} echouee : {exc}"
                ) from exc
            return

        actual = await self._collection_dimension()
        if actual != dimension:
            raise CollectionDimensionMismatchError(
                f"La collection {self._collection} attend des vecteurs de {actual} "
                f"dimensions, or l'embedder en produit {dimension}. "
                "Recreer la collection et re-ingerer, ou corriger embedding_model."
            )

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

        try:
            response = await self._client.query_points(
                self._collection,
                query=[float(component) for component in query_vector],
                limit=k,
            )
        except Exception as exc:
            raise VectorStoreError(f"Recherche dans {self._collection} echouee : {exc}") from exc

        return [_to_search_result(point) for point in response.points]

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

    async def _collection_dimension(self) -> int:
        """Lit la dimension declaree par la collection existante."""
        try:
            info = await self._client.get_collection(self._collection)
        except Exception as exc:
            raise VectorStoreError(
                f"Lecture de la collection {self._collection} echouee : {exc}"
            ) from exc

        params = info.config.params.vectors
        if not isinstance(params, models.VectorParams):
            raise VectorStoreError(
                f"La collection {self._collection} utilise des vecteurs nommes ; "
                "cette configuration n'est pas prise en charge."
            )
        return params.size


def _point_id(source: str, text: str) -> str:
    """Derive un identifiant reproductible a partir de la provenance et du texte.

    Le separateur nul evite les collisions entre couples differents dont la
    concatenation serait identique.
    """
    return str(uuid.uuid5(_POINT_NAMESPACE, f"{source}\x00{text}"))


def _to_search_result(point: Any) -> SearchResult:
    """Convertit un point Qdrant en `SearchResult`, provenance verifiee.

    Un point sans `text` ni `source` exploitables est refuse plutot que rendu
    avec des valeurs par defaut : mieux vaut une erreur bruyante qu'un extrait
    cite comme provenant de "inconnu" au milieu d'une reponse (SEC-08).
    """
    payload = point.payload or {}
    text = payload.get("text")
    source = payload.get("source")
    if not isinstance(text, str) or not isinstance(source, str):
        raise VectorStoreError(
            f"Point {point.id} sans provenance exploitable : "
            "champs 'text' et 'source' attendus dans le payload."
        )
    return SearchResult(text=text, source=source, score=float(point.score))
