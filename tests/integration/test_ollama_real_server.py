"""Test d'integration : parle au vrai serveur Ollama.

Deselectionne par defaut. Exige `ollama serve` et le modele configure. Lancer :

    pytest -m integration

Ce test existe parce que les tests unitaires ne peuvent pas le remplacer : un
transport factice rejoue nos propres hypotheses sur l'API d'Ollama. Si ces
hypotheses sont fausses — mauvais chemin, mauvais nom de champ, format de flux
different — les tests unitaires restent verts et la production casse. Seul un
appel reel verifie qu'on a bien lu le contrat.
"""

import pytest

from aisecassist.config import settings
from aisecassist.llm.ollama import OllamaProvider

pytestmark = [pytest.mark.anyio, pytest.mark.integration]

# Prompt volontairement trivial : on valide le contrat de l'API, pas la qualite
# du modele. Plus la generation est courte, plus le test est rapide.
_PROMPT = "Reponds uniquement par le mot OK, sans ponctuation."


async def test_complete_renvoie_du_texte_non_vide() -> None:
    async with OllamaProvider(
        base_url=settings.ollama_base_url,
        model=settings.ollama_model,
        timeout_s=settings.llm_timeout_s,
    ) as provider:
        reponse = await provider.complete(_PROMPT)

    assert reponse.strip() != ""


async def test_stream_emet_au_moins_un_fragment() -> None:
    fragments: list[str] = []

    async with OllamaProvider(
        base_url=settings.ollama_base_url,
        model=settings.ollama_model,
        timeout_s=settings.llm_timeout_s,
    ) as provider:
        async for fragment in provider.stream(_PROMPT):
            fragments.append(fragment)

    assert fragments != []
    assert "".join(fragments).strip() != ""
