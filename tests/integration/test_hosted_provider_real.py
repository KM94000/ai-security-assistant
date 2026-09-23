"""Verification du fournisseur heberge contre le vrai service (ticket 26).

Deselectionne par defaut, et **exclu de la CI** : exige un acces sortant et une
cle d'API que la CI n'a pas.

    # dans .env : LLM_PROVIDER=hosted et HOSTED_LLM_API_KEY=...
    pytest -m network

**Ce que ces tests prouvent, et que rien d'autre ne peut prouver.** Les tests
unitaires verifient notre traduction contre un transport factice : ils valident
ce que nous *croyons* etre le contrat du fournisseur. Ceux-ci valident le
contrat reel — y compris le point le plus fragile, l'aller-retour complet d'un
appel d'outil, ou l'API refuse la conversation si l'identifiant de l'appel n'est
pas renvoye a l'identique.

C'est aussi la verification de l'ADR-0003, qui affirme depuis le premier jour
que changer de fournisseur ne touche aucun module metier. Jusqu'ici, c'etait une
promesse.
"""

from __future__ import annotations

import anyio
import pytest

from aisecassist.config import settings
from aisecassist.llm.base import ChatMessage, ChatReply, ToolSpec
from aisecassist.llm.openai_compatible import OpenAICompatibleProvider

pytestmark = [
    pytest.mark.integration,
    pytest.mark.network,
    pytest.mark.skipif(
        not settings.hosted_llm_api_key,
        reason="HOSTED_LLM_API_KEY absente : verification du fournisseur heberge ignoree",
    ),
]

_OUTIL = ToolSpec(
    name="rechercher_corpus",
    description=(
        "Recherche des extraits dans le corpus de referentiels de securite. "
        "A utiliser pour toute question de fond."
    ),
    parameters={
        "type": "object",
        "properties": {"question": {"type": "string", "description": "La question a rechercher."}},
        "required": ["question"],
    },
)


def _provider() -> OpenAICompatibleProvider:
    return OpenAICompatibleProvider(
        base_url=settings.hosted_llm_base_url,
        model=settings.hosted_llm_model,
        api_key=settings.hosted_llm_api_key or "",
        timeout_s=settings.hosted_llm_timeout_s,
    )


def test_le_fournisseur_repond_a_une_question_simple() -> None:
    """Le contrat de base : une invite entre, du texte sort."""

    async def _executer() -> str:
        async with _provider() as provider:
            return await provider.complete(
                "Reponds par un seul mot : quel protocole chiffre le trafic web ?"
            )

    reponse = _executer_ou_expliquer(_executer)

    assert reponse.strip() != ""


def test_le_flux_arrive_par_fragments() -> None:
    """Le streaming est un contrat a part : meme API, autre forme de reponse."""

    async def _executer() -> list[str]:
        async with _provider() as provider:
            return [f async for f in provider.stream("Cite trois categories du OWASP Top 10.")]

    fragments = _executer_ou_expliquer(_executer)

    assert len(fragments) > 1, "un flux qui ne rend qu'un fragment n'est pas un flux"
    assert "".join(fragments).strip() != ""


def test_un_aller_retour_complet_dappel_doutil_est_accepte() -> None:
    """Le test qui compte : l'identifiant d'appel doit revenir a l'identique.

    Ce cas est celui qu'un transport factice ne peut pas valider. Si notre
    traduction se trompait — identifiant absent, ou remplace par le nom de
    l'outil — l'API rejetterait la conversation au second tour, et l'agent
    tomberait en production sans qu'aucun test unitaire ne l'ait vu.
    """

    async def _executer() -> ChatReply:
        async with _provider() as provider:
            premier = await provider.chat(
                [
                    ChatMessage(
                        role="system",
                        content=(
                            "Tu disposes d'un outil de recherche. Utilise-le pour toute "
                            "question de fond ; ne reponds jamais de memoire."
                        ),
                    ),
                    ChatMessage(
                        role="user",
                        content="Comment se defendre contre une injection de prompt indirecte ?",
                    ),
                ],
                [_OUTIL],
            )
            assert premier.tool_calls, "le modele n'a demande aucun outil"
            appel = premier.tool_calls[0]

            # Le second tour rejoue l'historique complet, resultat d'outil
            # compris : c'est la que l'identifiant doit correspondre.
            return await provider.chat(
                [
                    ChatMessage(role="user", content="Comment se defendre ?"),
                    ChatMessage(role="assistant", content="", tool_calls=(appel,)),
                    ChatMessage(
                        role="tool",
                        content="Separer structurellement les instructions du contenu recupere.",
                        tool_name=appel.name,
                        tool_call_id=appel.id,
                    ),
                ],
                [_OUTIL],
            )

    finale = _executer_ou_expliquer(_executer)

    assert finale.text.strip() != ""


def _executer_ou_expliquer(coroutine_factory):  # type: ignore[no-untyped-def]
    """Execute l'appel et rend l'echec lisible plutot que cryptique.

    Un quota atteint ou un nom de modele retire du catalogue produisent tous
    deux une `LLMError` ; sans ce rattrapage, le rapport d'echec ne dirait pas
    lequel des deux, ni quelle variable changer.
    """
    from aisecassist.llm.base import LLMError

    try:
        return anyio.run(coroutine_factory)
    except LLMError as exc:
        pytest.fail(
            f"Appel au fournisseur heberge echoue : {exc}\n"
            f"Verifier HOSTED_LLM_MODEL ({settings.hosted_llm_model}) "
            f"et HOSTED_LLM_BASE_URL ({settings.hosted_llm_base_url})."
        )
