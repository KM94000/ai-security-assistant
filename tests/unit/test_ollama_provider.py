"""Tests de `OllamaProvider`.

Aucun reseau, aucun serveur Ollama : le client httpx est remplace par un
transport factice. C'est tout l'interet d'avoir rendu le client injectable —
les tests restent rapides et deterministes (ADR-0002).
"""

from __future__ import annotations

import json
from collections.abc import Callable

import httpx
import pytest

from aisecassist.llm.base import LLMError
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
