"""Tests de `OpenAICompatibleProvider` (ticket 26).

Aucun reseau, aucune cle reelle : le client httpx est remplace par un transport
factice. Les memes garanties sont exigees que d'`OllamaProvider` — c'est le
point du ticket : deux implementations, un seul contrat.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from aisecassist.llm.base import ChatMessage, LLMError, ToolCall, ToolSpec
from aisecassist.llm.openai_compatible import OpenAICompatibleProvider

pytestmark = pytest.mark.anyio

Handler = Callable[[httpx.Request], httpx.Response]

_CLE = "gsk_ClefDeTestQuiNeDoitJamaisFuiter123456"


def _provider(handler: Handler) -> OpenAICompatibleProvider:
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="https://api.groq.test/openai/v1",
        headers={"Authorization": f"Bearer {_CLE}"},
    )
    return OpenAICompatibleProvider(
        base_url="https://api.groq.test/openai/v1",
        model="openai/gpt-oss-120b",
        api_key=_CLE,
        timeout_s=5.0,
        client=client,
    )


def _reponse(contenu: str = "Utilise un WAF.", **extra: Any) -> dict[str, Any]:
    return {"choices": [{"message": {"content": contenu, **extra}}]}


def _sse(*objets: dict[str, Any]) -> str:
    lignes = [f"data: {json.dumps(o)}" for o in objets]
    return "\n\n".join(lignes) + "\n\ndata: [DONE]\n\n"


def _delta(texte: str) -> dict[str, Any]:
    return {"choices": [{"delta": {"content": texte}}]}


# --- Reponse complete --------------------------------------------------------


async def test_complete_renvoie_la_reponse_du_modele() -> None:
    provider = _provider(lambda _: httpx.Response(200, json=_reponse()))

    assert await provider.complete("Comment mitiger une XSS ?") == "Utilise un WAF."


async def test_complete_envoie_le_modele_configure_sans_streaming() -> None:
    """Le contrat avec le fournisseur fait partie du comportement teste."""
    vues: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        vues.append(json.loads(request.content))
        return httpx.Response(200, json=_reponse())

    await _provider(handler).complete("question")

    assert vues[0]["model"] == "openai/gpt-oss-120b"
    assert vues[0]["stream"] is False
    assert vues[0]["messages"] == [{"role": "user", "content": "question"}]


async def test_la_cle_part_en_en_tete_dautorisation() -> None:
    vues: list[httpx.Headers] = []

    def handler(request: httpx.Request) -> httpx.Response:
        vues.append(request.headers)
        return httpx.Response(200, json=_reponse())

    await _provider(handler).complete("question")

    assert vues[0]["authorization"] == f"Bearer {_CLE}"


# --- Pannes ------------------------------------------------------------------


async def test_une_authentification_refusee_nomme_la_variable_a_verifier() -> None:
    """Un 401 a une cause actionnable : autant la dire, dans les logs.

    C'est le seul endroit ou le message d'erreur technique gagne a etre precis.
    Il part dans les logs du serveur, jamais vers le client, que la couche API
    sert avec un 503 generique.
    """
    provider = _provider(lambda _: httpx.Response(401, json={"error": "invalid api key"}))

    with pytest.raises(LLMError, match="HOSTED_LLM_API_KEY"):
        await provider.complete("question")


async def test_un_quota_atteint_est_distingue() -> None:
    provider = _provider(lambda _: httpx.Response(429))

    with pytest.raises(LLMError, match="429"):
        await provider.complete("question")


async def test_aucune_erreur_ne_contient_la_cle_dapi(caplog: pytest.LogCaptureFixture) -> None:
    """La cle voyage dans chaque requete : chaque chemin d'erreur peut la refleter.

    Le corps d'erreur d'un fournisseur reflete parfois l'en-tete recu. On ne le
    lit donc pas, et on ne retient que le code de statut.
    """
    provider = _provider(
        lambda _: httpx.Response(401, json={"error": {"message": f"bad key {_CLE}"}})
    )

    with caplog.at_level(logging.DEBUG):
        with pytest.raises(LLMError) as capture:
            await provider.complete("question")

    assert _CLE not in str(capture.value)
    assert _CLE not in caplog.text


async def test_une_reponse_illisible_devient_une_erreur_typee() -> None:
    provider = _provider(lambda _: httpx.Response(200, content=b"<html>503</html>"))

    with pytest.raises(LLMError, match="JSON invalide"):
        await provider.complete("question")


@pytest.mark.parametrize(
    "charge",
    [{}, {"choices": []}, {"choices": [{}]}, {"choices": [{"message": {}}]}],
    ids=["sans-choix", "choix-vide", "sans-message", "sans-contenu"],
)
async def test_une_reponse_de_forme_inattendue_est_refusee(charge: dict[str, Any]) -> None:
    """On ne fait jamais confiance a la forme de la reponse d'un service externe."""
    provider = _provider(lambda _: httpx.Response(200, json=charge))

    with pytest.raises(LLMError):
        await provider.complete("question")


# --- Flux --------------------------------------------------------------------


async def test_stream_rend_les_fragments_dans_lordre() -> None:
    provider = _provider(
        lambda _: httpx.Response(200, text=_sse(_delta("L'injection "), _delta("indirecte.")))
    )

    fragments = [f async for f in provider.stream("question")]

    assert fragments == ["L'injection ", "indirecte."]


async def test_stream_sarrete_sur_la_sentinelle_de_fin() -> None:
    """Sans cet arret, un fournisseur bavard apres `[DONE]` polluerait la reponse."""
    apres_la_fin = (
        _sse(_delta("utile")) + 'data: {"choices":[{"delta":{"content":"parasite"}}]}\n\n'
    )
    provider = _provider(lambda _: httpx.Response(200, text=apres_la_fin))

    assert [f async for f in provider.stream("question")] == ["utile"]


async def test_un_flux_refuse_devient_une_erreur_typee() -> None:
    provider = _provider(lambda _: httpx.Response(429, json={"error": "slow down"}))

    with pytest.raises(LLMError, match="429"):
        [f async for f in provider.stream("question")]


# --- Appels d'outils ---------------------------------------------------------


def _outil() -> ToolSpec:
    return ToolSpec(
        name="rechercher_corpus",
        description="Cherche dans le corpus.",
        parameters={"type": "object", "properties": {"question": {"type": "string"}}},
    )


async def test_chat_declare_les_outils_et_fixe_la_temperature_a_zero() -> None:
    vues: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        vues.append(json.loads(request.content))
        return httpx.Response(200, json=_reponse("ok"))

    await _provider(handler).chat([ChatMessage(role="user", content="q")], [_outil()])

    assert vues[0]["temperature"] == 0.0
    assert vues[0]["tools"][0]["function"]["name"] == "rechercher_corpus"


async def test_chat_rend_un_appel_doutil_avec_son_identifiant() -> None:
    """L'identifiant n'est pas decoratif : le fournisseur exige de le revoir.

    Sans lui, le message de resultat serait rejete par l'API au tour suivant.
    C'est ce qui justifie le champ `ToolCall.id` dans le type partage.
    """
    charge = _reponse(
        "",
        tool_calls=[
            {
                "id": "call_abc123",
                "type": "function",
                "function": {
                    "name": "rechercher_corpus",
                    "arguments": '{"question": "injection"}',
                },
            }
        ],
    )
    provider = _provider(lambda _: httpx.Response(200, json=charge))

    reponse = await provider.chat([ChatMessage(role="user", content="q")], [_outil()])

    assert reponse.tool_calls == (
        ToolCall(name="rechercher_corpus", arguments={"question": "injection"}, id="call_abc123"),
    )


async def test_des_arguments_json_invalides_donnent_un_dictionnaire_vide() -> None:
    """Un refus explicite de l'outil vaut mieux qu'une exception ici."""
    charge = _reponse(
        "",
        tool_calls=[
            {"id": "c1", "function": {"name": "rechercher_corpus", "arguments": "{pas du json"}}
        ],
    )
    provider = _provider(lambda _: httpx.Response(200, json=charge))

    reponse = await provider.chat([ChatMessage(role="user", content="q")], [_outil()])

    assert reponse.tool_calls[0].arguments == {}


async def test_un_appel_malforme_est_ecarte_sans_faire_tomber_la_requete(
    caplog: pytest.LogCaptureFixture,
) -> None:
    charge = _reponse("je reponds seul", tool_calls=["pas un objet", {"function": {}}])
    provider = _provider(lambda _: httpx.Response(200, json=charge))

    with caplog.at_level(logging.WARNING):
        reponse = await provider.chat([ChatMessage(role="user", content="q")], [_outil()])

    assert reponse.tool_calls == ()
    assert reponse.text == "je reponds seul"
    assert "ecarte" in caplog.text


async def test_un_resultat_doutil_reference_lappel_qui_la_provoque() -> None:
    """La difference de protocole que le ticket a revelee.

    Ollama apparie la demande et son resultat par l'ordre des messages ; cette
    API exige la reference explicite. Le champ voyage donc dans le type commun.
    """
    vues: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        vues.append(json.loads(request.content))
        return httpx.Response(200, json=_reponse("ok"))

    conversation = [
        ChatMessage(role="user", content="q"),
        ChatMessage(
            role="assistant",
            content="",
            tool_calls=(ToolCall(name="rechercher_corpus", arguments={}, id="call_9"),),
        ),
        ChatMessage(
            role="tool", content="extrait", tool_name="rechercher_corpus", tool_call_id="call_9"
        ),
    ]

    await _provider(handler).chat(conversation, [_outil()])

    envoyes = vues[0]["messages"]
    assert envoyes[1]["tool_calls"][0]["id"] == "call_9"
    assert envoyes[2]["tool_call_id"] == "call_9"


async def test_sans_identifiant_le_nom_sert_de_repli() -> None:
    """Un historique produit par Ollama doit rester rejouable ici.

    Les deux cotes font le meme repli, donc la conversation reste coherente —
    ce qui rend possible de changer de fournisseur sans repartir de zero.
    """
    vues: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        vues.append(json.loads(request.content))
        return httpx.Response(200, json=_reponse("ok"))

    conversation = [
        ChatMessage(
            role="assistant",
            content="",
            tool_calls=(ToolCall(name="rechercher_corpus", arguments={}),),
        ),
        ChatMessage(role="tool", content="extrait", tool_name="rechercher_corpus"),
    ]

    await _provider(handler).chat(conversation, [_outil()])

    envoyes = vues[0]["messages"]
    assert envoyes[0]["tool_calls"][0]["id"] == envoyes[1]["tool_call_id"] == "rechercher_corpus"
