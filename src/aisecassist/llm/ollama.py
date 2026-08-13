"""Implementation de `LLMProvider` adossee a un serveur Ollama (ADR-0003)."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from types import TracebackType
from typing import Any

import httpx

from aisecassist.llm.base import LLMError, LLMProvider

_GENERATE_PATH = "/api/generate"


class OllamaProvider(LLMProvider):
    """Appelle un serveur Ollama via son API HTTP.

    Le client httpx est injectable : les tests unitaires fournissent un
    transport factice, ce qui permet de verifier le contrat sans reseau ni
    serveur Ollama, donc sans test lent ni non deterministe (ADR-0002).
    """

    def __init__(
        self,
        base_url: str,
        model: str,
        timeout_s: float,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._model = model
        # On ne ferme que le client qu'on a cree soi-meme : fermer un client
        # injecte reviendrait a saboter l'objet d'un appelant qui le reutilise.
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(base_url=base_url, timeout=timeout_s)

    async def complete(self, prompt: str) -> str:
        payload = {"model": self._model, "prompt": prompt, "stream": False}
        try:
            response = await self._client.post(_GENERATE_PATH, json=payload)
            response.raise_for_status()
            data: Any = response.json()
        except httpx.HTTPError as exc:
            raise LLMError(_decrire("Appel a Ollama echoue", exc)) from exc
        except json.JSONDecodeError as exc:
            raise LLMError("Reponse d'Ollama illisible : JSON invalide") from exc

        return _extract_fragment(data, context="reponse complete")

    async def stream(self, prompt: str) -> AsyncIterator[str]:
        payload = {"model": self._model, "prompt": prompt, "stream": True}
        try:
            async with self._client.stream("POST", _GENERATE_PATH, json=payload) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line.strip():
                        continue
                    chunk = _parse_stream_line(line)
                    fragment = chunk.get("response")
                    if isinstance(fragment, str) and fragment:
                        yield fragment
                    # Ollama signale la fin par `done: true` sur le dernier
                    # objet. On s'arrete dessus plutot que d'attendre la
                    # fermeture du flux, qui peut trainer.
                    if chunk.get("done") is True:
                        return
        except httpx.HTTPError as exc:
            raise LLMError(_decrire("Flux Ollama interrompu", exc)) from exc

    async def aclose(self) -> None:
        """Libere le client HTTP si ce provider en est proprietaire."""
        if self._owns_client:
            await self._client.aclose()

    async def __aenter__(self) -> OllamaProvider:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.aclose()


def _decrire(contexte: str, exc: Exception) -> str:
    """Compose un message d'erreur qui reste exploitable dans les logs.

    httpx leve certaines exceptions — les depassements de delai notamment — dont
    le `str()` est vide. Interpoler l'exception seule produit alors un log du
    genre "Appel a Ollama echoue :", qui ne permet aucun diagnostic. Le nom de
    la classe, lui, est toujours present et suffit souvent a comprendre.
    """
    detail = str(exc).strip()
    return f"{contexte} ({type(exc).__name__})" + (f" : {detail}" if detail else "")


def _parse_stream_line(line: str) -> dict[str, Any]:
    """Decode une ligne NDJSON du flux Ollama."""
    try:
        chunk: Any = json.loads(line)
    except json.JSONDecodeError as exc:
        raise LLMError("Fragment non JSON recu d'Ollama") from exc
    if not isinstance(chunk, dict):
        raise LLMError("Fragment Ollama inattendu : objet JSON attendu")
    return chunk


def _extract_fragment(data: Any, *, context: str) -> str:
    """Extrait le champ `response` en verifiant sa forme.

    On ne fait jamais confiance a la forme de la reponse d'un service externe :
    un `data["response"]` direct ferait remonter un KeyError ou un TypeError
    opaque a des couches qui ne savent pas d'ou il vient.
    """
    if not isinstance(data, dict):
        raise LLMError(f"Reponse Ollama inattendue ({context}) : objet JSON attendu")
    fragment = data.get("response")
    if not isinstance(fragment, str):
        raise LLMError(
            f"Reponse Ollama inattendue ({context}) : champ 'response' absent ou non textuel"
        )
    return fragment
