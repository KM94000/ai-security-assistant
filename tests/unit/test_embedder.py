"""Tests de `SentenceTransformerEmbedder`.

Aucun modele n'est telecharge : le chargeur est remplace par un double. C'est
ce que permet le protocole `SentenceTransformerLike` — on teste notre logique
(paresse du chargement, ordre, garde-fou de dimension) sans dependre de torch.
"""

from __future__ import annotations

import pytest

from aisecassist.embeddings.base import DimensionMismatchError, EmbedderError
from aisecassist.embeddings.sentence_transformer import (
    SentenceTransformerEmbedder,
    SentenceTransformerLike,
)

pytestmark = pytest.mark.anyio


class _FakeModel:
    """Double minimal conforme au protocole `SentenceTransformerLike`."""

    def __init__(self, dimension: int) -> None:
        self._dimension = dimension

    def get_embedding_dimension(self) -> int | None:
        return self._dimension

    def encode(self, sentences: list[str]) -> list[list[float]]:
        # Un vecteur qui depend du texte : sans cela, un test d'ordre ne
        # prouverait rien puisque tous les vecteurs seraient identiques.
        return [[float(len(sentence))] * self._dimension for sentence in sentences]


class _CountingLoader:
    """Chargeur qui compte ses appels, pour verifier la paresse et le cache."""

    def __init__(self, dimension: int) -> None:
        self.dimension = dimension
        self.calls = 0
        self.revisions: list[str | None] = []

    def __call__(self, model_name: str, revision: str | None) -> SentenceTransformerLike:
        self.calls += 1
        self.revisions.append(revision)
        return _FakeModel(self.dimension)


def _embedder(expected: int = 384, actual: int | None = None) -> SentenceTransformerEmbedder:
    loader = _CountingLoader(actual if actual is not None else expected)
    return SentenceTransformerEmbedder("modele-de-test", expected, revision="rev", loader=loader)


def test_dimension_reflete_la_configuration() -> None:
    assert _embedder(expected=384).dimension == 384


def test_le_modele_nest_pas_charge_a_la_construction() -> None:
    """Construire un embedder ne doit declencher aucun telechargement."""
    loader = _CountingLoader(384)

    SentenceTransformerEmbedder("modele-de-test", 384, revision="rev", loader=loader)

    assert loader.calls == 0


async def test_embed_renvoie_un_vecteur_par_texte_dans_lordre() -> None:
    embedder = _embedder(expected=3)

    vectors = await embedder.embed(["aa", "bbbb", "c"])

    assert [vector[0] for vector in vectors] == [2.0, 4.0, 1.0]
    assert all(len(vector) == 3 for vector in vectors)


async def test_embed_sur_une_liste_vide_ne_charge_pas_le_modele() -> None:
    loader = _CountingLoader(384)
    embedder = SentenceTransformerEmbedder("modele-de-test", 384, revision="rev", loader=loader)

    assert await embedder.embed([]) == []
    assert loader.calls == 0


async def test_le_modele_nest_charge_quune_seule_fois() -> None:
    loader = _CountingLoader(384)
    embedder = SentenceTransformerEmbedder("modele-de-test", 384, revision="rev", loader=loader)

    await embedder.embed(["premier appel"])
    await embedder.embed(["second appel"])

    assert loader.calls == 1


async def test_un_modele_de_mauvaise_dimension_est_refuse() -> None:
    """Garde-fou central : une incoherence de dimension doit etre fatale.

    Un modele a 768 dimensions face a une collection creee pour 384 ne declenche
    aucune alerte visible : la recherche continue de repondre, en renvoyant des
    resultats silencieusement incoherents. On refuse donc de demarrer plutot que
    de degrader en silence (SECURITY.md, piege n.4).
    """
    embedder = _embedder(expected=384, actual=768)

    with pytest.raises(DimensionMismatchError) as excinfo:
        await embedder.embed(["question"])

    # Le message doit nommer les deux dimensions : c'est ce qui rend la panne
    # diagnosticable sans lire le code.
    assert "768" in str(excinfo.value)
    assert "384" in str(excinfo.value)


async def test_un_chargement_impossible_devient_une_erreur_metier() -> None:
    """L'appelant ne doit pas avoir a connaitre les exceptions de torch."""

    def failing_loader(model_name: str, revision: str | None) -> SentenceTransformerLike:
        raise OSError("modele introuvable")

    embedder = SentenceTransformerEmbedder(
        "modele-absent", 384, revision="rev", loader=failing_loader
    )

    with pytest.raises(EmbedderError):
        await embedder.embed(["question"])


async def test_la_revision_epinglee_est_transmise_au_chargement() -> None:
    """Sans cette transmission, l'epinglage ne serait qu'une valeur de configuration.

    Le seuil de pertinence est calibre sur des poids precis (ADR-0010). Si la
    revision se perdait entre la configuration et le chargement, le modele
    suivrait silencieusement les mises a jour du depot, et le seuil deriverait.
    """
    loader = _CountingLoader(384)
    embedder = SentenceTransformerEmbedder(
        "modele-de-test", 384, revision="d6cffd33", loader=loader
    )

    await embedder.embed(["question"])

    assert loader.revisions == ["d6cffd33"]
