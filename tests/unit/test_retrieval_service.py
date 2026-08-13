"""Tests du service de recherche (ticket 11)."""

from __future__ import annotations

import pytest

from aisecassist.retrieval.service import RetrievalError, RetrievalService
from tests.doubles import FakeEmbedder, FakeVectorStore, extrait

pytestmark = pytest.mark.anyio


async def test_retrouve_les_extraits_correspondants() -> None:
    store = FakeVectorStore([extrait("un"), extrait("deux")])
    service = RetrievalService(FakeEmbedder(), store, default_k=5)

    resultats = await service.retrieve("question")

    assert [r.text for r in resultats] == ["un", "deux"]


async def test_la_question_est_vectorisee_avant_la_recherche() -> None:
    embedder = FakeEmbedder()
    service = RetrievalService(embedder, FakeVectorStore(), default_k=5)

    await service.retrieve("comment mitiger une XSS ?")

    assert embedder.calls == [["comment mitiger une XSS ?"]]


async def test_utilise_le_k_de_configuration_par_defaut() -> None:
    store = FakeVectorStore()
    service = RetrievalService(FakeEmbedder(), store, default_k=3)

    await service.retrieve("question")

    assert store.last_k == 3


async def test_un_k_explicite_prime_sur_la_configuration() -> None:
    store = FakeVectorStore()
    service = RetrievalService(FakeEmbedder(), store, default_k=3)

    await service.retrieve("question", k=1)

    assert store.last_k == 1


async def test_un_corpus_sans_correspondance_renvoie_une_liste_vide() -> None:
    """Cas nominal, pas une erreur : le corpus peut ne rien contenir de pertinent."""
    service = RetrievalService(FakeEmbedder(), FakeVectorStore([]), default_k=5)

    assert await service.retrieve("question") == []


@pytest.mark.parametrize("question", ["", "   ", "\n\t "])
async def test_une_question_vide_est_refusee(question: str) -> None:
    """Controle redondant avec la validation pydantic, et assume comme tel.

    En M3 l'agent appellera ce service avec des arguments produits par un
    modele, donc non fiables. Un service qui ne se defend que parce qu'un
    appelant le fait a sa place cesse d'etre sur des qu'on change d'appelant.
    """
    service = RetrievalService(FakeEmbedder(), FakeVectorStore(), default_k=5)

    with pytest.raises(RetrievalError):
        await service.retrieve(question)


async def test_le_service_de_recherche_nappelle_jamais_le_modele() -> None:
    """Separation des responsabilites : `retrieval` ne connait pas `LLMProvider`.

    Verifie par construction — le service n'accepte pas de LLM dans son
    constructeur — ce que ce test documente explicitement.
    """
    import inspect

    parametres = inspect.signature(RetrievalService.__init__).parameters

    assert "llm" not in parametres
    assert set(parametres) == {"self", "embedder", "store", "default_k"}
