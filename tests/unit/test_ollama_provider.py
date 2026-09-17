"""Tests de `OllamaProvider`.

Aucun reseau, aucun serveur Ollama : le client httpx est remplace par un
transport factice. C'est tout l'interet d'avoir rendu le client injectable —
les tests restent rapides et deterministes (ADR-0002).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from aisecassist.llm.base import ChatMessage, LLMError, ToolCall, ToolSpec
from aisecassist.llm.ollama import OllamaProvider

pytestmark = pytest.mark.anyio

Handler = Callable[[httpx.Request], httpx.Response]


def _provider(handler: Handler) -> OllamaProvider:
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="http://ollama.test",
    )
    return OllamaProvider(
        base_url="http://ollama.test",
        model="llama3.1",
        timeout_s=5.0,
        client=client,
    )


def _ndjson(*objects: dict[str, object]) -> str:
    return "\n".join(json.dumps(obj) for obj in objects)


async def test_complete_renvoie_la_reponse_du_modele() -> None:
    provider = _provider(
        lambda _: httpx.Response(200, json={"response": "Utilise un WAF.", "done": True})
    )

    assert await provider.complete("Comment mitiger une XSS ?") == "Utilise un WAF."


async def test_complete_envoie_le_modele_configure_sans_streaming() -> None:
    """Le contrat avec Ollama fait partie du comportement teste.

    Une regression sur `stream` renverrait du NDJSON la ou `complete` attend un
    objet unique : l'erreur serait obscure et loin de sa cause.
    """
    recorded: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        recorded.append(json.loads(request.content))
        return httpx.Response(200, json={"response": "ok", "done": True})

    await _provider(handler).complete("question")

    assert recorded == [{"model": "llama3.1", "prompt": "question", "stream": False}]


async def test_complete_convertit_une_erreur_http_en_llmerror() -> None:
    provider = _provider(lambda _: httpx.Response(500, text="boom"))

    with pytest.raises(LLMError):
        await provider.complete("question")


async def test_complete_refuse_une_reponse_sans_champ_response() -> None:
    """Un service externe peut changer de forme : on ne lui fait pas confiance."""
    provider = _provider(lambda _: httpx.Response(200, json={"done": True}))

    with pytest.raises(LLMError):
        await provider.complete("question")


async def test_complete_refuse_une_reponse_qui_nest_pas_un_objet() -> None:
    provider = _provider(lambda _: httpx.Response(200, json=["pas", "un", "objet"]))

    with pytest.raises(LLMError):
        await provider.complete("question")


async def test_stream_emet_les_fragments_dans_lordre() -> None:
    body = _ndjson(
        {"response": "Il ", "done": False},
        {"response": "faut ", "done": False},
        {"response": "valider.", "done": False},
        {"response": "", "done": True},
    )
    provider = _provider(lambda _: httpx.Response(200, text=body))

    fragments = [fragment async for fragment in provider.stream("question")]

    assert fragments == ["Il ", "faut ", "valider."]


async def test_stream_sarrete_au_marqueur_done() -> None:
    """Rien de ce qui suit `done: true` ne doit atteindre l'appelant."""
    body = _ndjson(
        {"response": "debut", "done": False},
        {"response": "fin", "done": True},
        {"response": "NE DOIT PAS APPARAITRE", "done": False},
    )
    provider = _provider(lambda _: httpx.Response(200, text=body))

    fragments = [fragment async for fragment in provider.stream("question")]

    assert fragments == ["debut", "fin"]


async def test_stream_convertit_une_erreur_http_en_llmerror() -> None:
    provider = _provider(lambda _: httpx.Response(503, text="indisponible"))

    with pytest.raises(LLMError):
        [fragment async for fragment in provider.stream("question")]


async def test_stream_refuse_une_ligne_non_json() -> None:
    provider = _provider(lambda _: httpx.Response(200, text="ceci n'est pas du JSON"))

    with pytest.raises(LLMError):
        [fragment async for fragment in provider.stream("question")]


# --- Appel d'outils (ticket 19, ADR-0011) ------------------------------------

_SPEC = ToolSpec(
    name="rechercher_corpus",
    description="Recherche dans le corpus.",
    parameters={"type": "object", "properties": {"question": {"type": "string"}}},
)
_QUESTION = [ChatMessage(role="user", content="Comment mitiger une XSS ?")]


def _reponse_chat(**message: object) -> httpx.Response:
    return httpx.Response(200, json={"message": {"role": "assistant", **message}, "done": True})


async def test_chat_renvoie_le_texte_du_modele() -> None:
    provider = _provider(lambda _: _reponse_chat(content="  Utilise un WAF.  "))

    reponse = await provider.chat(_QUESTION, [_SPEC])

    assert reponse.text == "Utilise un WAF."
    assert reponse.tool_calls == ()


async def test_chat_renvoie_les_appels_doutils_demandes() -> None:
    provider = _provider(
        lambda _: _reponse_chat(
            content="",
            tool_calls=[
                {"function": {"name": "rechercher_corpus", "arguments": {"question": "xss"}}}
            ],
        )
    )

    reponse = await provider.chat(_QUESTION, [_SPEC])

    assert reponse.tool_calls == (
        ToolCall(name="rechercher_corpus", arguments={"question": "xss"}),
    )


async def test_chat_presente_les_outils_et_fige_la_temperature() -> None:
    """Le contrat avec Ollama fait partie du comportement teste.

    Sans `tools` dans la charge utile, le modele ne peut pas appeler d'outil ; et
    sans temperature nulle, il decrit parfois l'appel en texte au lieu de
    l'emettre (mesure a l'appui, ADR-0011).
    """
    recu: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        recu.append(json.loads(request.content))
        return _reponse_chat(content="ok")

    await _provider(handler).chat(_QUESTION, [_SPEC])

    charge = recu[0]
    assert charge["options"]["temperature"] == 0.0
    assert charge["stream"] is False
    assert charge["tools"][0]["function"]["name"] == "rechercher_corpus"
    assert charge["tools"][0]["type"] == "function"


async def test_chat_transmet_la_demande_et_le_resultat_doutil() -> None:
    """L'historique doit contenir la demande, puis le resultat qui lui repond."""
    recu: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        recu.append(json.loads(request.content))
        return _reponse_chat(content="fini")

    appel = ToolCall(name="rechercher_corpus", arguments={"question": "xss"})
    historique = [
        *_QUESTION,
        ChatMessage(role="assistant", content="", tool_calls=(appel,)),
        ChatMessage(role="tool", content="extrait", tool_name="rechercher_corpus"),
    ]

    await _provider(handler).chat(historique, [_SPEC])

    messages = recu[0]["messages"]
    assert messages[1]["tool_calls"][0]["function"]["name"] == "rechercher_corpus"
    assert messages[2] == {
        "role": "tool",
        "content": "extrait",
        "tool_name": "rechercher_corpus",
    }


async def test_chat_ecarte_un_appel_inexploitable_sans_faire_echouer_la_requete() -> None:
    """Un appel malforme est une erreur du modele, pas une panne du serveur.

    L'agent sait traiter l'absence d'appel — il repondra de lui-meme ou
    redemandera — la ou une exception ferait tomber la requete entiere.
    """
    provider = _provider(
        lambda _: _reponse_chat(
            content="",
            tool_calls=[
                {"function": {"arguments": {"question": "sans nom"}}},
                "pas un objet",
                {"function": {"name": "rechercher_corpus", "arguments": '{"question": "chaine"}'}},
            ],
        )
    )

    reponse = await provider.chat(_QUESTION, [_SPEC])

    # Seul l'appel exploitable subsiste, avec ses arguments decodes.
    assert reponse.tool_calls == (
        ToolCall(name="rechercher_corpus", arguments={"question": "chaine"}),
    )


async def test_chat_sur_une_reponse_sans_message_leve_une_erreur_metier() -> None:
    provider = _provider(lambda _: httpx.Response(200, json={"done": True}))

    with pytest.raises(LLMError):
        await provider.chat(_QUESTION, [_SPEC])


async def test_chat_sur_une_panne_reseau_leve_une_erreur_metier() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connexion refusee")

    with pytest.raises(LLMError):
        await _provider(handler).chat(_QUESTION, [_SPEC])
