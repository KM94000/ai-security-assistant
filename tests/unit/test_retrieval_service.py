"""Tests du service de recherche (ticket 11, seuil de pertinence : ADR-0010)."""

from __future__ import annotations

import logging

import pytest

from aisecassist.retrieval.service import RetrievalError, RetrievalService
from tests.doubles import FakeEmbedder, FakeVectorStore, extrait, make_retrieval

pytestmark = pytest.mark.anyio


async def test_retrouve_les_extraits_correspondants() -> None:
    service = make_retrieval(FakeVectorStore([extrait("un"), extrait("deux")]))

    resultats = await service.retrieve("question")

    assert [r.text for r in resultats] == ["un", "deux"]


async def test_la_question_est_vectorisee_avant_la_recherche() -> None:
    embedder = FakeEmbedder()
    service = make_retrieval(FakeVectorStore(), embedder=embedder)

    await service.retrieve("comment mitiger une XSS ?")

    assert embedder.calls == [["comment mitiger une XSS ?"]]


async def test_utilise_le_k_de_configuration_par_defaut() -> None:
    store = FakeVectorStore()
    service = make_retrieval(store, default_k=3)

    await service.retrieve("question")

    assert store.last_k == 3


async def test_un_k_explicite_prime_sur_la_configuration() -> None:
    store = FakeVectorStore()
    service = make_retrieval(store, default_k=3)

    await service.retrieve("question", k=1)

    assert store.last_k == 1


async def test_un_corpus_sans_correspondance_renvoie_une_liste_vide() -> None:
    """Cas nominal, pas une erreur : le corpus peut ne rien contenir de pertinent."""
    service = make_retrieval(FakeVectorStore([]))

    assert await service.retrieve("question") == []


@pytest.mark.parametrize("question", ["", "   ", "\n\t "])
async def test_une_question_vide_est_refusee(question: str) -> None:
    """Controle redondant avec la validation pydantic, et assume comme tel.

    En M3 l'agent appellera ce service avec des arguments produits par un
    modele, donc non fiables. Un service qui ne se defend que parce qu'un
    appelant le fait a sa place cesse d'etre sur des qu'on change d'appelant.
    """
    service = make_retrieval(FakeVectorStore())

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
    assert set(parametres) == {"self", "embedder", "store", "default_k", "min_score"}


# --- Seuil de pertinence (ADR-0010) ------------------------------------------


async def test_les_extraits_sous_le_seuil_sont_ecartes() -> None:
    """Sans seuil, la recherche renvoie toujours k extraits, meme hors sujet.

    Le refus « le corpus ne contient rien » ne se declenchait alors jamais, et un
    agent pose sur ce service tournerait sur des extraits sans rapport.
    """
    store = FakeVectorStore(
        [extrait("proche", score=0.80), extrait("lointain", score=0.30)],
    )
    service = make_retrieval(store, min_score=0.64)

    resultats = await service.retrieve("question")

    assert [r.text for r in resultats] == ["proche"]


async def test_un_extrait_exactement_au_seuil_est_conserve() -> None:
    """Le seuil est atteint, pas depasse : la borne est incluse."""
    service = make_retrieval(FakeVectorStore([extrait("limite", score=0.64)]), min_score=0.64)

    assert [r.text for r in await service.retrieve("question")] == ["limite"]


async def test_aucun_extrait_pertinent_donne_une_liste_vide() -> None:
    """La liste vide est la seule facon, pour ce service, de dire « je n'ai rien »."""
    store = FakeVectorStore([extrait("a", score=0.55), extrait("b", score=0.50)])
    service = make_retrieval(store, min_score=0.64)

    assert await service.retrieve("recette du cassoulet") == []


async def test_le_filtrage_preserve_lordre_de_pertinence() -> None:
    store = FakeVectorStore(
        [
            extrait("premier", score=0.90),
            extrait("ecarte", score=0.10),
            extrait("second", score=0.70),
        ],
    )
    service = make_retrieval(store, min_score=0.64)

    assert [r.text for r in await service.retrieve("question")] == ["premier", "second"]


async def test_le_seuil_ne_change_pas_le_nombre_dextraits_demandes() -> None:
    """Le seuil filtre ce qui revient ; il ne doit pas elargir ni reduire la recherche."""
    store = FakeVectorStore([extrait("a", score=0.9)])
    service = make_retrieval(store, default_k=5, min_score=0.64)

    await service.retrieve("question")

    assert store.last_k == 5


async def test_un_refus_est_journalise_avec_le_meilleur_score_mais_sans_la_question(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Le meilleur score sert a recalibrer le seuil ; la question n'a rien a faire en log.

    Une question peut contenir des donnees sensibles — un extrait de code, un nom
    de client, un identifiant. Journaliser le refus ne justifie pas de la copier
    dans un endroit souvent moins protege que la requete elle-meme.
    """
    question = "le mot de passe du compte admin-prod est-il expose ?"
    service = make_retrieval(FakeVectorStore([extrait("a", score=0.512)]), min_score=0.64)

    with caplog.at_level(logging.INFO, logger="aisecassist.retrieval.service"):
        await service.retrieve(question)

    assert "0.512" in caplog.text
    assert "0.640" in caplog.text
    assert question not in caplog.text
    assert "admin-prod" not in caplog.text
