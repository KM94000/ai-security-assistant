"""Tests du service de generation (ticket 12)."""

from __future__ import annotations

import pytest

from aisecassist.generation.prompt import REFUS_SANS_CONTEXTE
from aisecassist.llm.base import LLMError
from tests.doubles import (
    ExplodingLLM,
    FakeLLM,
    StreamingLLM,
    extrait,
    make_generation,
)

pytestmark = pytest.mark.anyio


async def test_renvoie_la_reponse_du_modele() -> None:
    service = make_generation(FakeLLM("Il faut valider les entrees."))

    resultat = await service.answer("question", [extrait("contenu")])

    assert resultat.answer == "Il faut valider les entrees."


async def test_les_sources_du_contexte_sont_remontees() -> None:
    service = make_generation(FakeLLM())

    resultat = await service.answer(
        "question",
        [extrait("a", source="owasp.md"), extrait("b", source="atlas.md")],
    )

    assert resultat.sources == ("owasp.md", "atlas.md")


async def test_une_source_citee_deux_fois_napparait_quune_fois() -> None:
    service = make_generation(FakeLLM())

    resultat = await service.answer(
        "question",
        [extrait("a", source="owasp.md"), extrait("b", source="owasp.md")],
    )

    assert resultat.sources == ("owasp.md",)


async def test_sans_extrait_le_modele_nest_pas_appele() -> None:
    """Un contexte vide revient a demander au modele de repondre de memoire.

    C'est precisement le mode de defaillance qu'un RAG est cense supprimer
    (LLM09, desinformation). On refuse explicitement, et on economise l'appel.
    """
    llm = FakeLLM()
    service = make_generation(llm)

    resultat = await service.answer("question", [])

    assert resultat.answer == REFUS_SANS_CONTEXTE
    assert resultat.sources == ()
    assert llm.prompts == []


async def test_le_prompt_transmis_contient_la_question_et_le_contexte() -> None:
    llm = FakeLLM()
    service = make_generation(llm)

    await service.answer("ma question", [extrait("mon extrait", source="src.md")])

    prompt = llm.prompts[0]
    assert "ma question" in prompt
    assert "mon extrait" in prompt
    assert "src.md" in prompt


@pytest.mark.parametrize("vide", ["", "   ", "\n\n"])
async def test_une_reponse_vide_du_modele_est_traitee_comme_une_panne(vide: str) -> None:
    """Une reponse vide accompagnee de sources est plus trompeuse qu'une erreur.

    Elle a la forme d'un resultat verifiable et n'affirme rien : le client voit
    des sources qui semblent etayer un contenu inexistant. On la traite comme ce
    qu'elle est, un echec de generation, et la couche API la rend en 503.
    """
    service = make_generation(FakeLLM(vide))

    with pytest.raises(LLMError):
        await service.answer("question", [extrait("contenu")])


async def test_une_panne_du_modele_remonte_telle_quelle() -> None:
    """Le service ne masque pas la panne : c'est la couche API qui la traduit en 503."""
    service = make_generation(ExplodingLLM(LLMError("ollama injoignable")))

    with pytest.raises(LLMError):
        await service.answer("question", [extrait("contenu")])


# --- Streaming (ticket 14) --------------------------------------------------


async def test_le_streaming_emet_les_fragments_dans_lordre() -> None:
    service = make_generation(StreamingLLM(["Il ", "faut ", "valider."]))

    fragments = [f async for f in service.stream_answer("question", [extrait("contenu")])]

    assert fragments == ["Il ", "faut ", "valider."]


async def test_le_streaming_sans_extrait_emet_le_refus_sans_appeler_le_modele() -> None:
    llm = StreamingLLM(["ne doit pas etre emis"])
    service = make_generation(llm)

    fragments = [f async for f in service.stream_answer("question", [])]

    assert fragments == [REFUS_SANS_CONTEXTE]
    assert llm.prompts == []


async def test_le_streaming_ignore_les_fragments_vides() -> None:
    service = make_generation(StreamingLLM(["a", "", "b"]))

    fragments = [f async for f in service.stream_answer("question", [extrait("contenu")])]

    assert fragments == ["a", "b"]


async def test_une_panne_pendant_le_streaming_remonte_telle_quelle() -> None:
    """C'est la couche API qui la traduit, et elle ne peut plus le faire en 503."""
    service = make_generation(ExplodingLLM(LLMError("ollama coupe en cours de flux")))

    with pytest.raises(LLMError):
        [f async for f in service.stream_answer("question", [extrait("contenu")])]
