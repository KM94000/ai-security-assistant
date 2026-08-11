"""Implementation d'`Embedder` adossee a sentence-transformers (ADR-0006)."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any, Protocol

import anyio.to_thread

from aisecassist.embeddings.base import DimensionMismatchError, Embedder, EmbedderError


class SentenceTransformerLike(Protocol):
    """Ce que l'on utilise reellement d'un `SentenceTransformer`.

    Decrire le strict necessaire, plutot que de dependre de la classe concrete,
    permet aux tests unitaires d'injecter un double sans installer torch — et
    documente noir sur blanc l'etendue de notre couplage au modele.
    """

    def get_embedding_dimension(self) -> int | None: ...

    def encode(self, sentences: list[str]) -> Any: ...


ModelLoader = Callable[[str], SentenceTransformerLike]


def load_sentence_transformer(model_name: str) -> SentenceTransformerLike:
    """Charge le modele depuis sentence-transformers.

    L'import est differe : importer torch coute plusieurs secondes et plusieurs
    centaines de Mo de memoire. Le faire au chargement du module penaliserait le
    demarrage de l'API et les tests qui n'en ont pas besoin.
    """
    from sentence_transformers import SentenceTransformer

    model: SentenceTransformerLike = SentenceTransformer(model_name)
    return model


class SentenceTransformerEmbedder(Embedder):
    """Vectorise en local avec un modele sentence-transformers.

    Le modele est charge paresseusement, a la premiere vectorisation : construire
    un embedder ne doit declencher ni telechargement ni chargement en memoire.
    """

    def __init__(
        self,
        model_name: str,
        expected_dimension: int,
        *,
        loader: ModelLoader | None = None,
    ) -> None:
        self._model_name = model_name
        self._expected_dimension = expected_dimension
        self._loader = loader or load_sentence_transformer
        self._model: SentenceTransformerLike | None = None

    @property
    def dimension(self) -> int:
        """Dimension attendue, telle que configuree.

        On renvoie la valeur de configuration et non celle du modele, pour ne
        pas forcer un telechargement de plusieurs dizaines de Mo sur une simple
        lecture d'attribut. La coherence entre les deux n'est pas supposee pour
        autant : elle est verifiee au chargement du modele, et une divergence y
        est fatale (`DimensionMismatchError`).
        """
        return self._expected_dimension

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        # `encode` est bloquant et gourmand en CPU. L'appeler directement
        # figerait la boucle d'evenements et donc toutes les autres requetes.
        return await anyio.to_thread.run_sync(self._embed_sync, list(texts))

    def _embed_sync(self, texts: list[str]) -> list[list[float]]:
        model = self._ensure_model()
        try:
            raw = model.encode(texts)
        except Exception as exc:  # noqa: BLE001 - retypage volontaire en erreur metier
            raise EmbedderError(f"Vectorisation echouee avec {self._model_name} : {exc}") from exc
        return _to_float_vectors(raw)

    def _ensure_model(self) -> SentenceTransformerLike:
        """Charge le modele au premier usage et verifie sa dimension."""
        if self._model is not None:
            return self._model

        try:
            model = self._loader(self._model_name)
        except Exception as exc:  # noqa: BLE001 - retypage volontaire en erreur metier
            raise EmbedderError(f"Chargement du modele {self._model_name} echoue : {exc}") from exc

        actual = model.get_embedding_dimension()
        if actual != self._expected_dimension:
            raise DimensionMismatchError(
                f"Le modele {self._model_name} produit des vecteurs de {actual} dimensions, "
                f"or la configuration en attend {self._expected_dimension}. "
                "Aligner embedding_dimension, puis recreer la collection et re-ingerer."
            )

        self._model = model
        return model


def _to_float_vectors(raw: Any) -> list[list[float]]:
    """Normalise la sortie du modele en listes de flottants natifs.

    sentence-transformers renvoie un tableau numpy ; les doubles de test
    renvoient des listes. On convertit dans les deux cas, car les clients
    vectoriels attendent des flottants Python serialisables en JSON.
    """
    vectors = raw.tolist() if hasattr(raw, "tolist") else raw
    return [[float(component) for component in vector] for vector in vectors]
