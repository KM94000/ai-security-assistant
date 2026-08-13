"""Tests du service de generation (ticket 12)."""

from __future__ import annotations

import pytest

from aisecassist.generation.prompt import REFUS_SANS_CONTEXTE
from aisecassist.generation.service import GenerationService
from aisecassist.llm.base import LLMError
from tests.doubles import ExplodingLLM, FakeLLM, extrait

pytestmark = pytest.mark.anyio


async def test_renvoie_la_reponse_du_modele() -> None:
    service = GenerationService(FakeLLM("Il faut valider les entrees."))

    resultat = await service.answer("question", [extrait("contenu")])

    assert resultat.answer == "Il faut valider les entrees."


async def test_les_sources_du_contexte_sont_remontees() -> None:
    service = GenerationService(FakeLLM())

    resultat = await service.answer(
        "question",
        [extrait("a", source="owasp.md"), extrait("b", source="atlas.md")],
    )

    assert resultat.sources == ("owasp.md", "atlas.md")


async def test_une_source_citee_deux_fois_napparait_quune_fois() -> None:
    service = GenerationService(FakeLLM())

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
    service = GenerationService(llm)

    resultat = await service.answer("question", [])

    assert resultat.answer == REFUS_SANS_CONTEXTE
    assert resultat.sources == ()
    assert llm.prompts == []


async def test_le_prompt_transmis_contient_la_question_et_le_contexte() -> None:
    llm = FakeLLM()
    service = GenerationService(llm)

    await service.answer("ma question", [extrait("mon extrait", source="src.md")])

    prompt = llm.prompts[0]
    assert "ma question" in prompt
    assert "mon extrait" in prompt
    assert "src.md" in prompt


async def test_une_panne_du_modele_remonte_telle_quelle() -> None:
    """Le service ne masque pas la panne : c'est la couche API qui la traduit en 503."""
    service = GenerationService(ExplodingLLM(LLMError("ollama injoignable")))

    with pytest.raises(LLMError):
        await service.answer("question", [extrait("contenu")])
